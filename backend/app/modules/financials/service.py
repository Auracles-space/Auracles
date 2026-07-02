"""Business services for financial transactions and payouts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from cryptography.fernet import InvalidToken
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import exists, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.security import (
    decrypt_payout_provider_account_id,
    encrypt_payout_provider_account_id,
    hash_payout_provider_account_id,
)
from app.integrations import s3, stripe
from app.integrations.stripe import StripeProviderError
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.collections.models import CollectionEarningAllocation
from app.modules.developer.models import PartnerCommission
from app.modules.financials.models import (
    Escrow,
    Payout,
    PayoutAccount,
    PlatformConfig,
    Transaction,
)
from app.modules.financials.schemas import (
    EarningsResponse,
    InvoiceGenerationResponse,
    PaymentMethodDeleteResponse,
    PaymentMethodResponse,
    PaymentMethodSetupResponse,
    PaymentMethodsResponse,
    PayoutAccountDeleteResponse,
    PayoutAccountOnboardRequest,
    PayoutAccountOnboardResponse,
    PayoutAccountResponse,
    PayoutAccountsResponse,
    PayoutRequest,
    PayoutResponse,
    PayoutsResponse,
    PurchaseHistoryItem,
    PurchaseHistoryResponse,
    PurchaseRequest,
    PurchaseResponse,
    RefundResponse,
)
from app.modules.frameworks.models import Framework, License
from app.modules.frameworks.models_artifact import ArtifactDownload
from app.modules.invoicing import service as invoicing_service
from app.workers.tasks.financials import generate_invoice_pdf
from app.workers.tasks.payouts import process_payout

INVOICE_URL_TTL_SECONDS = 900
PAYOUT_CLAIM_STATUSES = {"pending", "processing", "completed"}
# Earning classes for payout-balance derivation. Marketplace earnings clear
# after the refund window at the marketplace commission rate; attestation
# earnings clear immediately at the attestation commission rate (Module 6a).
_MARKETPLACE_EARNING_CLASS = "marketplace"
_ATTESTATION_EARNING_CLASS = "attestation"


def _masked_provider_ref(provider_ref: str) -> str:
    """Return a log-safe provider reference that preserves only the last chars."""
    return f"****{provider_ref[-4:]}" if len(provider_ref) > 4 else "****"


def _provider_account_id_plaintext(payout_account: PayoutAccount) -> str:
    """Return the provider account id, decrypting rows written after Slice 14."""
    try:
        return decrypt_payout_provider_account_id(payout_account.provider_account_id)
    except InvalidToken:
        # Local/dev rows may predate the encryption migration. Keep reads working
        # while all new writes use encrypted storage and lookup hashes.
        return payout_account.provider_account_id


def _payout_account_response(payout_account: PayoutAccount) -> PayoutAccountResponse:
    """Map a payout account row to safe Contributor-facing metadata."""
    provider_account_id = _provider_account_id_plaintext(payout_account)
    return PayoutAccountResponse(
        id=payout_account.id,
        provider="stripe",
        account_type=payout_account.account_type,
        provider_account_ref=_masked_provider_ref(provider_account_id),
        is_default=payout_account.is_default,
        verified_at=payout_account.verified_at,
        created_at=payout_account.created_at,
    )


def _normalise_money(amount: Decimal) -> Decimal:
    """Return a two-decimal money value for persisted payment records."""
    return amount.quantize(Decimal("0.01"))


def _payout_response(payout: Payout) -> PayoutResponse:
    """Map a payout row to Contributor-facing response data."""
    return PayoutResponse(
        id=payout.id,
        payout_account_id=payout.payout_account_id,
        amount=payout.amount,
        currency=payout.currency,
        commission_deducted=payout.commission_deducted,
        net_amount=payout.net_amount,
        status=payout.status,
        provider_ref=(
            _masked_provider_ref(payout.provider_ref) if payout.provider_ref else None
        ),
        initiated_at=payout.initiated_at,
        completed_at=payout.completed_at,
    )


async def _refund_window_hours(db: AsyncSession) -> int:
    """Return the configured self-serve purchase refund window."""
    configured = await db.scalar(
        select(PlatformConfig.value).where(PlatformConfig.key == "refund_window_hours")
    )
    if configured is None:
        return 48
    try:
        return int(configured)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Refund window configuration is invalid.",
        ) from exc


async def _platform_decimal_config(
    db: AsyncSession,
    *,
    key: str,
    default: Decimal,
) -> Decimal:
    """Return a decimal platform configuration value."""
    configured = await db.scalar(
        select(PlatformConfig.value).where(PlatformConfig.key == key)
    )
    if configured is None:
        return default
    try:
        return Decimal(configured)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{key} configuration is invalid.",
        ) from exc


async def _commission_rate(db: AsyncSession) -> Decimal:
    """Return the configured platform commission rate."""
    return await _platform_decimal_config(
        db,
        key="commission_rate",
        default=Decimal("0.15"),
    )


async def _attestation_commission_rate(db: AsyncSession) -> Decimal:
    """Return the configured Attestation settlement commission rate.

    Attestation earnings settle at a lower platform commission than the
    framework marketplace (10% vs 15%); see Module 6a design §4.1.
    """
    return await _platform_decimal_config(
        db,
        key="attestation_commission_rate",
        default=Decimal("0.10"),
    )


async def _minimum_payout(db: AsyncSession, currency: str) -> Decimal:
    """Return the configured minimum payout for a currency."""
    config_key = f"min_payout_{currency.lower()}"
    default = Decimal("50.00") if currency.upper() == "USD" else Decimal("0.00")
    return _normalise_money(
        await _platform_decimal_config(db, key=config_key, default=default)
    )


async def _sum_transactions(
    db: AsyncSession,
    *,
    contributor_id: UUID,
    currency: str,
    earning_class: str,
    before: datetime | None = None,
    after_or_at: datetime | None = None,
) -> Decimal:
    """Return gross completed earnings for one earning class.

    ``earning_class`` selects which transaction types count:
    ``_MARKETPLACE_EARNING_CLASS`` covers framework purchases and released
    project milestones; ``_ATTESTATION_EARNING_CLASS`` covers released
    attestation fees.
    """
    released_escrow_exists = exists(
        select(Escrow.id).where(
            Escrow.ref_id == Transaction.ref_id,
            Escrow.ref_type == Transaction.ref_type,
            Escrow.status == "released",
        )
    )
    if earning_class == _ATTESTATION_EARNING_CLASS:
        class_filter = or_(
            (Transaction.transaction_type == "attestation_fee")
            & (Transaction.ref_type == "attestation")
            & released_escrow_exists
        )
    else:
        class_filter = or_(
            Transaction.transaction_type == "purchase",
            (
                (Transaction.transaction_type == "milestone")
                & (Transaction.ref_type == "project_milestone")
                & released_escrow_exists
            ),
        )
    filters = [
        Transaction.payee_id == contributor_id,
        class_filter,
        Transaction.status == "completed",
        Transaction.currency == currency,
    ]
    if before is not None:
        filters.append(Transaction.created_at < before)
    if after_or_at is not None:
        filters.append(Transaction.created_at >= after_or_at)
    value = await db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(*filters)
    )
    return _normalise_money(Decimal(value or "0"))


async def _claimed_payouts(
    db: AsyncSession,
    *,
    contributor_id: UUID,
    currency: str,
) -> Decimal:
    """Return net payout amounts already claimed from available earnings."""
    value = await db.scalar(
        select(func.coalesce(func.sum(Payout.net_amount), 0)).where(
            Payout.contributor_id == contributor_id,
            Payout.currency == currency,
            Payout.status.in_(PAYOUT_CLAIM_STATUSES),
        )
    )
    return _normalise_money(Decimal(value or "0"))


def _blended_commission_rate(
    cleared_gross: Decimal, cleared_net: Decimal
) -> Decimal:
    """Return the effective commission rate across cleared earnings.

    Returns 0 when there are no cleared earnings, avoiding division by zero.
    Framework/project-only earners resolve to exactly the marketplace rate,
    attestation-only earners to the attestation rate, and mixed earners to a
    blended rate. Trailing zeros are stripped so a pure 15% earner serializes
    as ``"0.15"`` rather than ``"0.1500"``.
    """
    if cleared_gross <= 0:
        return Decimal("0")
    rate = (Decimal("1") - (cleared_net / cleared_gross)).quantize(Decimal("0.0001"))
    return rate.normalize()


async def _available_payout_balance(
    db: AsyncSession,
    *,
    contributor_id: UUID,
    currency: str,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Return gross, pending, available, claimed, and blended-commission balances.

    Marketplace earnings (framework purchases, released project milestones)
    clear after the refund window at the marketplace commission rate.
    Attestation earnings clear immediately on release at the attestation
    commission rate. The returned commission rate is the effective blended
    rate across all cleared earnings (Module 6a design §5, §6).
    """
    refund_window_hours = await _refund_window_hours(db)
    marketplace_rate = await _commission_rate(db)
    attestation_rate = await _attestation_commission_rate(db)
    cutoff = datetime.now(UTC) - timedelta(hours=refund_window_hours)
    marketplace_gross = await _sum_transactions(
        db,
        contributor_id=contributor_id,
        currency=currency,
        earning_class=_MARKETPLACE_EARNING_CLASS,
    )
    marketplace_pending = await _sum_transactions(
        db,
        contributor_id=contributor_id,
        currency=currency,
        earning_class=_MARKETPLACE_EARNING_CLASS,
        after_or_at=cutoff,
    )
    marketplace_cleared_gross = await _sum_transactions(
        db,
        contributor_id=contributor_id,
        currency=currency,
        earning_class=_MARKETPLACE_EARNING_CLASS,
        before=cutoff,
    )
    attestation_gross = await _sum_transactions(
        db,
        contributor_id=contributor_id,
        currency=currency,
        earning_class=_ATTESTATION_EARNING_CLASS,
    )
    claimed = await _claimed_payouts(
        db,
        contributor_id=contributor_id,
        currency=currency,
    )
    marketplace_cleared_net = _normalise_money(
        marketplace_cleared_gross * (Decimal("1") - marketplace_rate)
    )
    attestation_cleared_net = _normalise_money(
        attestation_gross * (Decimal("1") - attestation_rate)
    )
    total_cleared_gross = marketplace_cleared_gross + attestation_gross
    total_cleared_net = marketplace_cleared_net + attestation_cleared_net
    available = max(_normalise_money(total_cleared_net - claimed), Decimal("0.00"))
    gross_revenue = marketplace_gross + attestation_gross
    pending_clearance = marketplace_pending
    commission_rate = _blended_commission_rate(total_cleared_gross, total_cleared_net)
    return gross_revenue, pending_clearance, available, claimed, commission_rate


async def _lock_contributor_financials(
    db: AsyncSession,
    *,
    contributor_id: UUID,
) -> None:
    """Serialize payout balance mutations for one Contributor."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"payout:{contributor_id}"},
    )


async def _count_license_downloads(db: AsyncSession, license_id: UUID) -> int:
    """Return how many artifacts have been downloaded under a license."""
    return int(
        await db.scalar(
            select(func.count())
            .select_from(ArtifactDownload)
            .where(ArtifactDownload.license_id == license_id)
        )
        or 0
    )


async def _verify_sensitive_payment_method_change(
    db: AsyncSession,
    redis: Redis,
    operator: User,
    totp_code: str,
) -> None:
    """Require a valid TOTP or backup code before changing payment methods."""
    await auth_service.verify_totp_for_sensitive_action(
        db=db,
        redis=redis,
        user=operator,
        code=totp_code,
    )
    await db.commit()


async def _has_active_payout_account(db: AsyncSession, user_id: UUID) -> bool:
    """Return whether the Contributor has any non-deleted payout account."""
    existing_id = await db.scalar(
        select(PayoutAccount.id)
        .where(
            PayoutAccount.user_id == user_id,
            PayoutAccount.deleted_at.is_(None),
        )
        .limit(1)
    )
    return existing_id is not None


async def create_payment_method_setup(
    db: AsyncSession,
    redis: Redis,
    operator: User,
    *,
    totp_code: str,
) -> PaymentMethodSetupResponse:
    """Create/reuse a Stripe Customer and return a SetupIntent client secret."""
    operator_id = operator.id
    customer_id = operator.stripe_customer_id

    await _verify_sensitive_payment_method_change(
        db=db,
        redis=redis,
        operator=operator,
        totp_code=totp_code,
    )

    try:
        if customer_id is None:
            customer = await stripe.create_customer(
                email=operator.email,
                name=operator.display_name,
                idempotency_key=f"stripe_customer:{operator_id}",
            )
            customer_id = customer.id
        setup_intent = await stripe.create_setup_intent(customer_id=customer_id)
    except StripeProviderError as exc:
        logger.bind(
            module="financials",
            action="create_payment_method_setup",
            user_id=operator_id,
        ).error("stripe_payment_method_setup_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        if operator.stripe_customer_id is None:
            operator.stripe_customer_id = customer_id
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="payment_method_added",
            target_type="user",
            target_id=operator_id,
            metadata={
                "provider": "stripe",
                "setup_intent_ref": _masked_provider_ref(setup_intent.id),
            },
        )

    logger.bind(
        module="financials",
        action="create_payment_method_setup",
        user_id=operator_id,
    ).info("payment_method_added")
    return PaymentMethodSetupResponse(
        provider="stripe",
        setup_intent_id=setup_intent.id,
        client_secret=setup_intent.client_secret,
    )


async def list_payment_methods(
    db: AsyncSession,
    operator: User,
) -> PaymentMethodsResponse:
    """Return safe metadata for the Operator's provider-held payment methods."""
    del db
    customer_id = operator.stripe_customer_id
    if customer_id is None:
        return PaymentMethodsResponse(payment_methods=[])

    try:
        payment_methods = await stripe.list_payment_methods(customer_id=customer_id)
    except StripeProviderError as exc:
        logger.bind(
            module="financials",
            action="list_payment_methods",
            user_id=operator.id,
        ).error("stripe_payment_method_list_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    return PaymentMethodsResponse(
        payment_methods=[
            PaymentMethodResponse(
                id=payment_method.id,
                provider="stripe",
                type=payment_method.type,
                brand=payment_method.brand,
                last4=payment_method.last4,
                exp_month=payment_method.exp_month,
                exp_year=payment_method.exp_year,
            )
            for payment_method in payment_methods
        ]
    )


async def list_framework_purchases(
    db: AsyncSession,
    operator: User,
    *,
    page: int,
    page_size: int,
) -> PurchaseHistoryResponse:
    """Return the Operator's paginated Framework purchase history."""
    base_filters = (
        Transaction.payer_id == operator.id,
        Transaction.transaction_type == "purchase",
    )
    total = int(
        await db.scalar(
            select(func.count()).select_from(Transaction).where(*base_filters)
        )
        or 0
    )
    rows = await db.execute(
        select(Transaction, Framework, License)
        .join(Framework, Framework.id == Transaction.ref_id)
        .outerjoin(License, License.transaction_id == Transaction.id)
        .where(*base_filters)
        .order_by(Transaction.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return PurchaseHistoryResponse(
        items=[
            PurchaseHistoryItem(
                transaction_id=transaction.id,
                framework_id=framework.id,
                framework_title=framework.title,
                amount=transaction.amount,
                currency=transaction.currency,
                status=transaction.status,
                provider="stripe",
                license_id=license_row.id if license_row is not None else None,
                license_type=(
                    license_row.license_type if license_row is not None else None
                ),
                purchased_at=transaction.created_at,
            )
            for transaction, framework, license_row in rows.all()
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


async def _load_operator_purchase(
    db: AsyncSession,
    *,
    operator_id: UUID,
    transaction_id: UUID,
) -> Transaction:
    """Load an Operator-owned Framework purchase transaction."""
    transaction = await db.scalar(
        select(Transaction)
        .where(
            Transaction.id == transaction_id,
            Transaction.payer_id == operator_id,
            Transaction.transaction_type == "purchase",
        )
        .with_for_update()
    )
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purchase not found.",
        )
    return transaction


async def get_framework_purchase_invoice(
    db: AsyncSession,
    operator: User,
    *,
    transaction_id: UUID,
) -> Response:
    """Return a generated invoice URL or queue invoice PDF generation."""
    transaction = await _load_operator_purchase(
        db=db,
        operator_id=operator.id,
        transaction_id=transaction_id,
    )
    if transaction.status not in {"completed", "refunded"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invoice is only available for settled purchases.",
        )

    from app.core.config import get_settings

    settings = get_settings()
    invoice = await invoicing_service.issue_invoice(
        db,
        doc_type=invoicing_service.DOC_SALES_INVOICE,
        series=invoicing_service.SERIES_SALES,
        source_ref_type="transaction",
        source_ref_id=transaction_id,
        currency=transaction.currency,
        subtotal=transaction.amount,
        seller=invoicing_service.seller_identity(settings),
        buyer_name=operator.display_name,
        buyer_email=operator.email,
    )
    await db.commit()

    key = invoice.s3_key
    if s3.storage.object_exists(settings.s3_reports_bucket, key):
        invoice_url = s3.storage.presigned_get(
            settings.s3_reports_bucket,
            key,
            INVOICE_URL_TTL_SECONDS,
        )
        return RedirectResponse(url=invoice_url, status_code=status.HTTP_302_FOUND)

    generate_invoice_pdf.delay(str(transaction_id))
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
        content=InvoiceGenerationResponse(
            transaction_id=transaction_id,
            status="generating",
        ).model_dump(mode="json"),
    )


async def delete_payment_method(
    db: AsyncSession,
    redis: Redis,
    operator: User,
    *,
    payment_method_id: str,
    totp_code: str,
) -> PaymentMethodDeleteResponse:
    """Detach a provider-held payment method after TOTP and ownership checks."""
    customer_id = operator.stripe_customer_id
    if customer_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment method not found.",
        )

    await _verify_sensitive_payment_method_change(
        db=db,
        redis=redis,
        operator=operator,
        totp_code=totp_code,
    )

    try:
        owned_methods = await stripe.list_payment_methods(customer_id=customer_id)
        if not any(method.id == payment_method_id for method in owned_methods):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment method not found.",
            )
        detached_id = await stripe.detach_payment_method(
            payment_method_id=payment_method_id,
        )
    except HTTPException:
        raise
    except StripeProviderError as exc:
        logger.bind(
            module="financials",
            action="delete_payment_method",
            user_id=operator.id,
        ).error("stripe_payment_method_detach_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await write_audit(
            db=db,
            actor_id=operator.id,
            action="payment_method_removed",
            target_type="user",
            target_id=operator.id,
            metadata={
                "provider": "stripe",
                "payment_method_ref": _masked_provider_ref(detached_id),
            },
        )

    logger.bind(
        module="financials",
        action="delete_payment_method",
        user_id=operator.id,
    ).info("payment_method_removed")
    return PaymentMethodDeleteResponse(
        provider="stripe",
        payment_method_id=detached_id,
        removed=True,
    )


async def _create_pending_purchase_transaction(
    db: AsyncSession,
    *,
    operator_id: UUID,
    customer_id: str,
    contributor_id: UUID,
    framework_id: UUID,
    amount: Decimal,
    currency: str,
) -> UUID:
    """Persist the local purchase record before provider confirmation."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        operator = await db.get(User, operator_id)
        if operator is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )
        if operator.stripe_customer_id is None:
            operator.stripe_customer_id = customer_id
        transaction = Transaction(
            payer_id=operator_id,
            payee_id=contributor_id,
            amount=amount,
            currency=currency,
            platform_commission=Decimal("0.00"),
            net_amount=amount,
            transaction_type="purchase",
            status="pending",
            provider="stripe",
            ref_id=framework_id,
            ref_type="framework",
        )
        db.add(transaction)
        await db.flush()
        transaction_id = transaction.id
    return transaction_id


async def _mark_purchase_initiated(
    db: AsyncSession,
    *,
    operator_id: UUID,
    transaction_id: UUID,
    provider_ref: str,
    framework_id: UUID,
    license_type: str,
) -> None:
    """Attach provider intent metadata and audit a checkout start."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        transaction = await db.get(Transaction, transaction_id)
        if transaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase transaction not found.",
            )
        transaction.provider_ref = provider_ref
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="purchase_initiated",
            target_type="transaction",
            target_id=transaction.id,
            metadata={
                "provider": "stripe",
                "provider_ref": _masked_provider_ref(provider_ref),
                "framework_id": str(framework_id),
                "license_type": license_type,
            },
        )


async def _mark_purchase_failed(
    db: AsyncSession,
    *,
    operator_id: UUID,
    transaction_id: UUID,
    framework_id: UUID,
    license_type: str,
) -> None:
    """Mark checkout failure without granting a License."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        transaction = await db.get(Transaction, transaction_id)
        if transaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase transaction not found.",
            )
        transaction.status = "failed"
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="purchase_failed",
            target_type="transaction",
            target_id=transaction.id,
            metadata={
                "provider": "stripe",
                "framework_id": str(framework_id),
                "license_type": license_type,
            },
        )


async def create_framework_purchase(
    db: AsyncSession,
    operator: User,
    *,
    framework_id: UUID,
    payload: PurchaseRequest,
) -> PurchaseResponse:
    """Create a pending transaction and Stripe PaymentIntent for checkout."""
    operator_id = operator.id
    operator_email = operator.email
    operator_display_name = operator.display_name
    customer_id = operator.stripe_customer_id

    framework = await db.scalar(
        select(Framework)
        .join(User, User.id == Framework.contributor_id)
        .where(
            Framework.id == framework_id,
            Framework.status == "published",
            Framework.deleted_at.is_(None),
            User.suspended_at.is_(None),
        )
    )
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )

    contributor_id = framework.contributor_id
    if contributor_id == operator_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot purchase your own Framework.",
        )

    existing_license_id = await db.scalar(
        select(License.id)
        .where(
            License.framework_id == framework_id,
            License.operator_id == operator_id,
            License.status == "active",
        )
        .limit(1)
    )
    if existing_license_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Framework is already licensed.",
        )

    if payload.license_type not in framework.license_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Selected license type is not available for this Framework.",
        )

    amount = _normalise_money(framework.price)
    currency = framework.currency.upper()
    if currency != "USD":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only USD purchases are supported.",
        )

    try:
        if customer_id is None:
            customer = await stripe.create_customer(
                email=operator_email,
                name=operator_display_name,
                idempotency_key=f"stripe_customer:{operator_id}",
            )
            customer_id = customer.id
    except StripeProviderError as exc:
        logger.bind(
            module="financials",
            action="create_framework_purchase",
            user_id=operator_id,
            framework_id=framework_id,
        ).error("stripe_customer_create_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    transaction_id = await _create_pending_purchase_transaction(
        db=db,
        operator_id=operator_id,
        customer_id=customer_id,
        contributor_id=contributor_id,
        framework_id=framework_id,
        amount=amount,
        currency=currency,
    )

    try:
        payment_intent = await stripe.create_payment_intent(
            customer_id=customer_id,
            amount=amount,
            currency=currency,
            metadata={
                "transaction_id": str(transaction_id),
                "kind": "purchase",
                "framework_id": str(framework_id),
                "license_type": payload.license_type,
            },
            idempotency_key=f"purchase:{transaction_id}",
        )
    except StripeProviderError as exc:
        await _mark_purchase_failed(
            db=db,
            operator_id=operator_id,
            transaction_id=transaction_id,
            framework_id=framework_id,
            license_type=payload.license_type,
        )
        logger.bind(
            module="financials",
            action="create_framework_purchase",
            user_id=operator_id,
            framework_id=framework_id,
            transaction_id=transaction_id,
        ).error("stripe_payment_intent_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    await _mark_purchase_initiated(
        db=db,
        operator_id=operator_id,
        transaction_id=transaction_id,
        provider_ref=payment_intent.id,
        framework_id=framework_id,
        license_type=payload.license_type,
    )
    logger.bind(
        module="financials",
        action="create_framework_purchase",
        user_id=operator_id,
        framework_id=framework_id,
        transaction_id=transaction_id,
    ).info("purchase_initiated")
    return PurchaseResponse(
        transaction_id=transaction_id,
        provider="stripe",
        client_secret=payment_intent.client_secret,
    )


async def _load_refundable_purchase(
    db: AsyncSession,
    *,
    operator_id: UUID,
    transaction_id: UUID,
) -> tuple[Transaction, License]:
    """Load and validate the local purchase state before provider refund."""
    transaction = await db.scalar(
        select(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.payer_id == operator_id,
            Transaction.transaction_type == "purchase",
        )
    )
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purchase not found.",
        )
    if transaction.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only completed purchases can be refunded.",
        )
    if transaction.provider != "stripe" or transaction.provider_ref is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Purchase is missing refundable provider metadata.",
        )

    license_row = await db.scalar(
        select(License)
        .where(
            License.transaction_id == transaction.id,
            License.operator_id == operator_id,
            License.status == "active",
        )
        .with_for_update()
    )
    if license_row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Active purchase license not found.",
        )

    refund_window_hours = await _refund_window_hours(db)
    if datetime.now(UTC) - transaction.created_at > timedelta(
        hours=refund_window_hours
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Refund window has expired.",
        )
    if await _count_license_downloads(db, license_row.id) > 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Purchases with artifact downloads cannot be refunded.",
        )
    return transaction, license_row


async def _count_collection_license_downloads(
    db: AsyncSession,
    *,
    license_ids: list[UUID],
) -> int:
    """Return artifact download count across all minted Collection licenses."""
    if not license_ids:
        return 0
    return int(
        await db.scalar(
            select(func.count())
            .select_from(ArtifactDownload)
            .where(ArtifactDownload.license_id.in_(license_ids))
        )
        or 0
    )


async def _load_refundable_collection_purchase(
    db: AsyncSession,
    *,
    operator_id: UUID,
    transaction: Transaction,
) -> list[License]:
    """Load and validate a collection purchase for all-or-nothing refund."""
    if transaction.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only completed purchases can be refunded.",
        )
    if transaction.provider != "stripe" or transaction.provider_ref is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Purchase is missing refundable provider metadata.",
        )
    if transaction.ref_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Collection purchase is missing collection metadata.",
        )

    refund_window_hours = await _refund_window_hours(db)
    if datetime.now(UTC) - transaction.created_at > timedelta(
        hours=refund_window_hours
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Refund window has expired.",
        )

    licenses = list(
        (
            await db.execute(
                select(License)
                .where(
                    License.transaction_id == transaction.id,
                    License.operator_id == operator_id,
                    License.status == "active",
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if not licenses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Active collection purchase licenses not found.",
        )
    if any(
        license_row.source != "collection"
        or license_row.collection_id != transaction.ref_id
        for license_row in licenses
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Collection purchase licenses are inconsistent.",
        )

    license_ids = [license_row.id for license_row in licenses]
    if await _count_collection_license_downloads(db, license_ids=license_ids) > 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Purchases with artifact downloads cannot be refunded.",
        )
    return licenses


async def _void_partner_commission_for_refund(
    db: AsyncSession,
    *,
    transaction_id: UUID,
    operator_id: UUID,
) -> None:
    """Void pending/cleared Partner commission tied to a refunded purchase."""
    commission = await db.scalar(
        select(PartnerCommission).where(
            PartnerCommission.transaction_id == transaction_id
        )
    )
    if commission is None or commission.status == "voided":
        return
    if commission.status == "paid":
        logger.bind(
            module="financials",
            action="void_partner_commission_for_refund",
            transaction_id=transaction_id,
        ).critical("paid_partner_commission_refund_detected")
        return

    commission.status = "voided"
    await write_audit(
        db=db,
        actor_id=operator_id,
        action="partner_commission_voided",
        target_type="partner_commission",
        target_id=commission.id,
        metadata={
            "transaction_id": str(transaction_id),
            "reason": "purchase_refunded",
        },
    )


async def refund_framework_purchase(
    db: AsyncSession,
    operator: User,
    *,
    transaction_id: UUID,
) -> RefundResponse:
    """Refund an eligible Framework or Collection purchase."""
    operator_id = operator.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        collection_transaction = await db.scalar(
            select(Transaction)
            .where(
                Transaction.id == transaction_id,
                Transaction.payer_id == operator_id,
                Transaction.transaction_type == "purchase",
                Transaction.ref_type == "collection",
            )
            .with_for_update()
        )
        if collection_transaction is not None:
            licenses = await _load_refundable_collection_purchase(
                db=db,
                operator_id=operator_id,
                transaction=collection_transaction,
            )
            assert collection_transaction.provider_ref is not None
            try:
                refund = await stripe.create_refund(
                    payment_intent_id=collection_transaction.provider_ref,
                    amount=_normalise_money(collection_transaction.amount),
                    currency=collection_transaction.currency.upper(),
                    idempotency_key=f"refund:{transaction_id}",
                )
            except StripeProviderError as exc:
                logger.bind(
                    module="financials",
                    action="refund_collection_purchase",
                    user_id=operator_id,
                    transaction_id=transaction_id,
                ).error("stripe_refund_failed", error=str(exc))
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Payment provider is unavailable.",
                ) from exc

            license_ids = [license_row.id for license_row in licenses]
            if (
                await _count_collection_license_downloads(
                    db,
                    license_ids=license_ids,
                )
                > 0
            ):
                logger.bind(
                    module="financials",
                    action="refund_collection_purchase",
                    user_id=operator_id,
                    transaction_id=transaction_id,
                ).critical("refund_download_race_after_provider_refund")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Refund provider call completed but a download was "
                        "recorded."
                    ),
                )

            collection_transaction.status = "refunded"
            for license_row in licenses:
                license_row.status = "revoked"
            allocations = list(
                (
                    await db.execute(
                        select(CollectionEarningAllocation)
                        .where(
                            CollectionEarningAllocation.transaction_id
                            == collection_transaction.id
                        )
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            for allocation in allocations:
                await db.delete(allocation)
            await write_audit(
                db=db,
                actor_id=operator_id,
                action="collection_refunded",
                target_type="transaction",
                target_id=collection_transaction.id,
                metadata={
                    "provider": "stripe",
                    "refund_ref": _masked_provider_ref(refund.id),
                    "collection_id": str(collection_transaction.ref_id),
                    "license_ids": [str(license_id) for license_id in license_ids],
                    "framework_ids": [
                        str(license_row.framework_id) for license_row in licenses
                    ],
                },
            )
            logger.bind(
                module="financials",
                action="refund_collection_purchase",
                user_id=operator_id,
                transaction_id=transaction_id,
            ).info("collection_refunded")
            return RefundResponse(
                transaction_id=transaction_id,
                provider="stripe",
                refund_id=refund.id,
                status="refunded",
            )

        transaction, license_row = await _load_refundable_purchase(
            db=db,
            operator_id=operator_id,
            transaction_id=transaction_id,
        )
        assert transaction.provider_ref is not None
        try:
            refund = await stripe.create_refund(
                payment_intent_id=transaction.provider_ref,
                amount=_normalise_money(transaction.amount),
                currency=transaction.currency.upper(),
                idempotency_key=f"refund:{transaction_id}",
            )
        except StripeProviderError as exc:
            logger.bind(
                module="financials",
                action="refund_framework_purchase",
                user_id=operator_id,
                transaction_id=transaction_id,
            ).error("stripe_refund_failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Payment provider is unavailable.",
            ) from exc

        if await _count_license_downloads(db, license_row.id) > 0:
            logger.bind(
                module="financials",
                action="refund_framework_purchase",
                user_id=operator_id,
                transaction_id=transaction_id,
            ).critical("refund_download_race_after_provider_refund")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Refund provider call completed but a download was recorded.",
            )
        transaction.status = "refunded"
        license_row.status = "revoked"
        await _void_partner_commission_for_refund(
            db,
            transaction_id=transaction.id,
            operator_id=operator_id,
        )
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="purchase_refunded",
            target_type="transaction",
            target_id=transaction.id,
            metadata={
                "provider": "stripe",
                "refund_ref": _masked_provider_ref(refund.id),
                "license_id": str(license_row.id),
            },
        )

    logger.bind(
        module="financials",
        action="refund_framework_purchase",
        user_id=operator_id,
        transaction_id=transaction_id,
    ).info("purchase_refunded")
    return RefundResponse(
        transaction_id=transaction_id,
        provider="stripe",
        refund_id=refund.id,
        status="refunded",
    )


async def get_contributor_earnings(
    db: AsyncSession,
    contributor: User,
) -> EarningsResponse:
    """Return refund-safe Contributor earnings balances."""
    currency = "USD"
    (
        gross_revenue,
        pending_clearance,
        available,
        _,
        commission_rate,
    ) = await _available_payout_balance(
        db,
        contributor_id=contributor.id,
        currency=currency,
    )
    return EarningsResponse(
        currency=currency,
        gross_revenue=gross_revenue,
        pending_clearance=pending_clearance,
        available_balance=available,
        commission_rate=commission_rate,
        minimum_payout=await _minimum_payout(db, currency),
    )


async def request_payout(
    db: AsyncSession,
    redis: Redis,
    contributor: User,
    payload: PayoutRequest,
) -> PayoutResponse:
    """Create a pending payout request and queue provider transfer processing."""
    contributor_id = contributor.id
    currency = payload.currency.upper()
    if currency != "USD":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only USD payouts are supported.",
        )

    requested_net = _normalise_money(payload.amount)
    minimum = await _minimum_payout(db, currency)
    if requested_net < minimum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Minimum payout is ${minimum}.",
        )

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await _lock_contributor_financials(db, contributor_id=contributor_id)
        payout_account = await db.scalar(
            select(PayoutAccount)
            .where(
                PayoutAccount.id == payload.payout_account_id,
                PayoutAccount.user_id == contributor_id,
                PayoutAccount.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if payout_account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payout account not found.",
            )
        if payout_account.verified_at is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Payout account is not verified.",
            )

        _, _, available, _, commission_rate = await _available_payout_balance(
            db,
            contributor_id=contributor_id,
            currency=currency,
        )
        if requested_net > available:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Requested payout exceeds available balance.",
            )

        contributor_for_2fa = await db.get(User, contributor_id, with_for_update=True)
        if contributor_for_2fa is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )
        await auth_service.verify_totp_for_sensitive_action(
            db=db,
            redis=redis,
            user=contributor_for_2fa,
            code=payload.totp_code,
        )
        gross_drawdown = _normalise_money(
            requested_net / (Decimal("1") - commission_rate)
        )
        commission_deducted = _normalise_money(gross_drawdown - requested_net)
        payout = Payout(
            contributor_id=contributor_id,
            payout_account_id=payload.payout_account_id,
            amount=gross_drawdown,
            currency=currency,
            commission_deducted=commission_deducted,
            net_amount=requested_net,
            status="pending",
        )
        db.add(payout)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="payout_requested",
            target_type="payout",
            target_id=payout.id,
            metadata={
                "currency": currency,
                "net_amount": str(requested_net),
                "commission_deducted": str(commission_deducted),
            },
        )

    try:
        process_payout.delay(str(payout.id))
    except Exception as exc:
        logger.bind(
            module="financials",
            action="request_payout",
            user_id=contributor_id,
            payout_id=payout.id,
        ).error("payout_task_dispatch_failed", error=str(exc))

    logger.bind(
        module="financials",
        action="request_payout",
        user_id=contributor_id,
        payout_id=payout.id,
    ).info("payout_requested")
    return _payout_response(payout)


async def list_payouts(
    db: AsyncSession,
    contributor: User,
) -> PayoutsResponse:
    """List payout history for the Contributor."""
    payouts = (
        (
            await db.execute(
                select(Payout)
                .where(Payout.contributor_id == contributor.id)
                .order_by(Payout.initiated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return PayoutsResponse(payouts=[_payout_response(payout) for payout in payouts])


async def onboard_payout_account(
    db: AsyncSession,
    contributor: User,
    payload: PayoutAccountOnboardRequest,
) -> PayoutAccountOnboardResponse:
    """Create a provider-held payout destination for a KYC-verified Contributor."""
    contributor_id = contributor.id

    # Reuse the existing active Stripe account to avoid orphan express accounts
    existing_account = await db.scalar(
        select(PayoutAccount).where(
            PayoutAccount.user_id == contributor_id,
            PayoutAccount.provider == payload.provider,
            PayoutAccount.deleted_at.is_(None),
        )
    )

    if existing_account is not None:
        try:
            provider_account_id = _provider_account_id_plaintext(existing_account)
            account_link = await stripe.create_account_link(
                account_id=provider_account_id,
                refresh_url=payload.refresh_url,
                return_url=payload.return_url,
            )
            onboarding_url = account_link.url
        except StripeProviderError as exc:
            logger.bind(
                module="financials",
                action="onboard_payout_account",
                user_id=contributor_id,
            ).error("payout_account_provider_failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Payout provider is unavailable.",
            ) from exc

        logger.bind(
            module="financials",
            action="onboard_payout_account",
            user_id=contributor_id,
        ).info("payout_account_onboard_reinitiated")

        return PayoutAccountOnboardResponse(
            provider=payload.provider,
            onboarding_url=onboarding_url,
            payout_account=_payout_account_response(existing_account),
        )

    try:
        stripe_account = await stripe.create_express_account(
            email=contributor.email,
            country=payload.country,
        )
        account_link = await stripe.create_account_link(
            account_id=stripe_account.id,
            refresh_url=payload.refresh_url,
            return_url=payload.return_url,
        )
        provider_account_id = stripe_account.id
        account_type = "express"
        onboarding_url = account_link.url
    except StripeProviderError as exc:
        logger.bind(
            module="financials",
            action="onboard_payout_account",
            user_id=contributor_id,
        ).error("payout_account_provider_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payout provider is unavailable.",
        ) from exc

    if db.in_transaction():
        await db.rollback()
    try:
        async with db.begin():
            payout_account = PayoutAccount(
                user_id=contributor_id,
                provider=payload.provider,
                provider_account_id=encrypt_payout_provider_account_id(
                    provider_account_id
                ),
                provider_account_lookup_hash=hash_payout_provider_account_id(
                    provider_account_id
                ),
                account_type=account_type,
                is_default=not await _has_active_payout_account(db, contributor_id),
            )
            db.add(payout_account)
            await db.flush()
            await write_audit(
                db=db,
                actor_id=contributor_id,
                action="payout_account_onboarded",
                target_type="payout_account",
                target_id=payout_account.id,
                metadata={
                    "provider": payload.provider,
                    "account_type": account_type,
                    "provider_account_ref": _masked_provider_ref(provider_account_id),
                },
            )
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payout account already exists.",
        ) from exc

    logger.bind(
        module="financials",
        action="onboard_payout_account",
        user_id=contributor_id,
    ).info("payout_account_onboarded")
    return PayoutAccountOnboardResponse(
        provider=payload.provider,
        onboarding_url=onboarding_url,
        payout_account=_payout_account_response(payout_account),
    )


async def list_payout_accounts(
    db: AsyncSession,
    contributor: User,
) -> PayoutAccountsResponse:
    """List active payout accounts for the authenticated Contributor."""
    payout_accounts = (
        (
            await db.execute(
                select(PayoutAccount)
                .where(
                    PayoutAccount.user_id == contributor.id,
                    PayoutAccount.deleted_at.is_(None),
                )
                .order_by(PayoutAccount.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return PayoutAccountsResponse(
        payout_accounts=[
            _payout_account_response(payout_account)
            for payout_account in payout_accounts
        ]
    )


async def delete_payout_account(
    db: AsyncSession,
    redis: Redis,
    contributor: User,
    *,
    payout_account_id: UUID,
    totp_code: str,
) -> PayoutAccountDeleteResponse:
    """Soft-delete an owned payout account after TOTP confirmation."""
    contributor_id = contributor.id
    payout_account = await db.scalar(
        select(PayoutAccount).where(
            PayoutAccount.id == payout_account_id,
            PayoutAccount.user_id == contributor_id,
            PayoutAccount.deleted_at.is_(None),
        )
    )
    if payout_account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payout account not found.",
        )

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        payout_account = await db.scalar(
            select(PayoutAccount)
            .where(
                PayoutAccount.id == payout_account_id,
                PayoutAccount.user_id == contributor_id,
                PayoutAccount.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if payout_account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payout account not found.",
            )
        contributor_for_2fa = await db.get(User, contributor_id, with_for_update=True)
        if contributor_for_2fa is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )
        await auth_service.verify_totp_for_sensitive_action(
            db=db,
            redis=redis,
            user=contributor_for_2fa,
            code=totp_code,
        )
        payout_account.deleted_at = datetime.now(UTC)
        payout_account.is_default = False
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="payout_account_deleted",
            target_type="payout_account",
            target_id=payout_account.id,
            metadata={
                "provider": payout_account.provider,
                "account_type": payout_account.account_type,
                "provider_account_ref": _masked_provider_ref(
                    _provider_account_id_plaintext(payout_account)
                ),
            },
        )

    logger.bind(
        module="financials",
        action="delete_payout_account",
        user_id=contributor_id,
    ).info("payout_account_deleted")
    return PayoutAccountDeleteResponse(
        payout_account_id=payout_account_id,
        deleted=True,
    )
