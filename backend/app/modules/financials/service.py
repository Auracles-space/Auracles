"""Business services for financial transactions and payouts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from cryptography.fernet import InvalidToken
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse, Response
from loguru import logger
from sqlalchemy import ColumnElement, exists, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.currency import platform_currency
from app.core.rate_limit import RateLimiter, RedisCounter
from app.core.security import (
    decrypt_payout_provider_account_id,
    encrypt_payout_provider_account_id,
    hash_payout_provider_account_id,
)
from app.integrations import paystack, s3, stripe
from app.integrations.payment_router import PaymentProvider, select_provider
from app.integrations.paystack import PaystackProviderError
from app.integrations.stripe import StripeProviderError
from app.modules.auth.models import User
from app.modules.collections.models import CollectionEarningAllocation
from app.modules.developer.models import PartnerCommission
from app.modules.financials import commission, refund_intents
from app.modules.financials import invoices as financials_invoices
from app.modules.financials.ledger import record_financial_event
from app.modules.financials.models import (
    Escrow,
    FinancialEvent,
    Payout,
    PayoutAccount,
    PlatformConfig,
    Transaction,
)
from app.modules.financials.schemas import (
    EarningsResponse,
    InvoiceGenerationResponse,
    OrgEarningsResponse,
    OrgInvoiceListItem,
    OrgInvoicesResponse,
    OrgPayoutAccountOnboardRequest,
    OrgPayoutHistoryItem,
    OrgPayoutHistoryResponse,
    OrgPurchaseListItem,
    OrgPurchasesResponse,
    PaymentMethodDeleteResponse,
    PaymentMethodResponse,
    PaymentMethodSetupResponse,
    PaymentMethodsResponse,
    PayoutAccountDeleteResponse,
    PayoutAccountOnboardRequest,
    PayoutAccountOnboardResponse,
    PayoutAccountResolveRequest,
    PayoutAccountResolveResponse,
    PayoutAccountResponse,
    PayoutAccountsResponse,
    PayoutBank,
    PayoutBanksResponse,
    PayoutEligibility,
    PayoutEligibilityReason,
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
from app.modules.frameworks.pricing import resolve_license_price
from app.modules.invoicing.models import Invoice
from app.modules.organizations import notifications as org_notifications
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgCapability,
    OrgLegalProfile,
    OrgMember,
)
from app.modules.organizations.operator_service import operator_capability_active
from app.shared.errors import error_detail
from app.shared.schemas.download import DownloadUrlResponse
from app.workers.tasks.financials import generate_invoice_pdf
from app.workers.tasks.payouts import process_payout

INVOICE_URL_TTL_SECONDS = 900
PAYOUT_CLAIM_STATUSES = {"pending", "processing", "completed"}
# How many owners may collect through one bank account before an admin has to
# look. Set above the honest ceiling — a person, their contributor org, and
# their attestor org is three — so only a funnel meets it.
MAX_PAYOUT_DESTINATION_OWNERS = 3
# Resolving turns an account number into a person's name, so the ceiling is
# set for someone correcting one typo, not for walking the number space.
PAYOUT_ACCOUNT_RESOLVE_RATE_LIMITER = RateLimiter(
    namespace="payout_account_resolve", limit=15, window=3600
)
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
    """Return the configured platform commission rate.

    Consulted only at settlement time (via `financials.commission`) and for
    display defaults — settled earnings carry their own stamped rate.
    """
    return await commission.marketplace_commission_rate(db)


async def _attestation_commission_rate(db: AsyncSession) -> Decimal:
    """Return the configured Attestation settlement commission rate.

    Attestation earnings settle at a lower platform commission than the
    framework marketplace (10% vs 15%); see Module 6a design §4.1.
    """
    return await commission.attestation_commission_rate(db)


# Fallback payout floors, used only if `min_payout_<ccy>` is missing from
# platform_config. A floor of zero would let a payout be worth less than the
# provider's own transfer fee, so every settleable currency needs a real number.
# Both keys are admin-editable, and the seeded rows are the operative values —
# these are the last resort for a database that never received them.
_MINIMUM_PAYOUT_DEFAULTS = {
    "USD": Decimal("50.00"),
    "NGN": Decimal("50000.00"),
}


async def _minimum_payout(db: AsyncSession, currency: str) -> Decimal:
    """Return the configured minimum payout for a currency."""
    normalized = currency.upper()
    config_key = f"min_payout_{normalized.lower()}"
    default = _MINIMUM_PAYOUT_DEFAULTS.get(normalized, Decimal("0.00"))
    return _normalise_money(
        await _platform_decimal_config(db, key=config_key, default=default)
    )


def earning_class_filter(earning_class: str) -> ColumnElement[bool]:
    """Return the SQL predicate for transactions that credit a payee's balance.

    ``_MARKETPLACE_EARNING_CLASS`` covers framework and collection purchases
    and released project milestones; ``_ATTESTATION_EARNING_CLASS`` covers
    released attestation fees. Callers add ``status == 'completed'``. Shared
    by the individual and org balances and by Treasury, so "money a payee has
    earned" has exactly one definition.
    """
    released_escrow_exists = exists(
        select(Escrow.id).where(
            Escrow.ref_id == Transaction.ref_id,
            Escrow.ref_type == Transaction.ref_type,
            Escrow.status == "released",
        )
    )
    if earning_class == _ATTESTATION_EARNING_CLASS:
        return (
            (Transaction.transaction_type == "attestation_fee")
            & (Transaction.ref_type == "attestation")
            & released_escrow_exists
        )
    return or_(
        Transaction.transaction_type == "purchase",
        (
            (Transaction.transaction_type == "milestone")
            & (Transaction.ref_type == "project_milestone")
            & released_escrow_exists
        ),
    )


async def _sum_transactions(
    db: AsyncSession,
    *,
    contributor_id: UUID,
    currency: str,
    earning_class: str,
    before: datetime | None = None,
    after_or_at: datetime | None = None,
    net: bool = False,
) -> Decimal:
    """Return completed earnings for one earning class, gross or net.

    ``earning_class`` selects which transaction types count:
    ``_MARKETPLACE_EARNING_CLASS`` covers framework purchases and released
    project milestones; ``_ATTESTATION_EARNING_CLASS`` covers released
    attestation fees. ``net`` sums the sale-time-stamped ``net_amount``
    instead of the gross ``amount``, so a later commission-rate change never
    reprices settled earnings.
    """
    class_filter = earning_class_filter(earning_class)
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
    column = Transaction.net_amount if net else Transaction.amount
    value = await db.scalar(select(func.coalesce(func.sum(column), 0)).where(*filters))
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


def _blended_commission_rate(cleared_gross: Decimal, cleared_net: Decimal) -> Decimal:
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
    clear after the refund window; attestation earnings clear immediately on
    release. Net values sum each sale's stamped `net_amount`, so the rate in
    force when a sale settled — not today's configured rate — is what the
    Contributor withdraws at. The returned commission rate is the effective
    blended rate across all cleared earnings (Module 6a design §5, §6).
    """
    refund_window_hours = await _refund_window_hours(db)
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
    marketplace_cleared_net = await _sum_transactions(
        db,
        contributor_id=contributor_id,
        currency=currency,
        earning_class=_MARKETPLACE_EARNING_CLASS,
        before=cutoff,
        net=True,
    )
    attestation_gross = await _sum_transactions(
        db,
        contributor_id=contributor_id,
        currency=currency,
        earning_class=_ATTESTATION_EARNING_CLASS,
    )
    attestation_cleared_net = await _sum_transactions(
        db,
        contributor_id=contributor_id,
        currency=currency,
        earning_class=_ATTESTATION_EARNING_CLASS,
        net=True,
    )
    claimed = await _claimed_payouts(
        db,
        contributor_id=contributor_id,
        currency=currency,
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


async def resolve_payout_account_name(
    *,
    redis: RedisCounter,
    actor_id: UUID,
    payload: PayoutAccountResolveRequest,
) -> PayoutAccountResolveResponse:
    """Return the account holder's name for a NUBAN, registering nothing.

    Rate limited per caller because the lookup turns an account number into a
    person's name. Legitimate use is a handful of tries while typing one
    account; anything beyond that is walking the number space to harvest
    names, which the bank's own customers never consented to.

    Args:
        redis: Redis connection backing the rate-limit counter.
        actor_id: Caller the limit is counted against.
        payload: The account number and bank code to look up.

    Returns:
        The name the bank holds for the account.

    Raises:
        HTTPException(422): Paystack could not resolve the account.
        HTTPException(429): The caller exceeded the lookup limit.
    """
    await PAYOUT_ACCOUNT_RESOLVE_RATE_LIMITER.check(redis, str(actor_id))
    try:
        account_name = await paystack.resolve_account_name(
            account_number=payload.account_number,
            bank_code=payload.bank_code,
        )
    except PaystackProviderError as exc:
        logger.bind(
            module="financials",
            action="resolve_payout_account_name",
            user_id=actor_id,
        ).info("payout_account_resolve_failed")
        # 422 rather than 502: the common cause by far is a number that does
        # not exist at that bank, which is the caller's to correct.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "That account number could not be found at the bank you "
                "selected. Check both and try again."
            ),
        ) from exc
    return PayoutAccountResolveResponse(account_name=account_name)


async def _count_payout_destination_owners(
    db: AsyncSession,
    *,
    provider: str,
    lookup_hash: str,
) -> int:
    """Count the live owners already collecting through one bank account."""
    rows = await db.execute(
        select(PayoutAccount.user_id, PayoutAccount.org_id).where(
            PayoutAccount.provider == provider,
            PayoutAccount.provider_account_lookup_hash == lookup_hash,
            PayoutAccount.deleted_at.is_(None),
        )
    )
    return len({(user_id, org_id) for user_id, org_id in rows})


async def _guard_payout_destination_sharing(
    db: AsyncSession,
    *,
    provider: str,
    lookup_hash: str,
    actor_id: UUID,
    owner_ref: dict[str, str],
) -> int:
    """Refuse a bank account that already collects for too many owners.

    Sharing itself is legitimate and common: a sole trader's own payout
    account and their organization's are routinely the same NUBAN. What the cap
    catches is one account collecting for many separate identities, which is
    the shape of a payout funnel rather than a sole trader, and it sits well
    above the honest cases so they never meet it.

    The count is read outside the insert transaction, so two simultaneous
    registrations can both pass it. That is deliberate: the cap exists to
    trigger a human look, not to guard money, and both registrations are
    recorded either way.

    Args:
        db: Async session; must not hold an open transaction on refusal.
        provider: Payment provider the destination belongs to.
        lookup_hash: Keyed hash of the provider account id.
        actor_id: User the refusal is audited against.
        owner_ref: Owner identifiers to carry into the audit metadata.

    Returns:
        How many owners already hold this destination, this one excluded.

    Raises:
        HTTPException(422): If admitting another owner would pass the cap.
    """
    owner_count = await _count_payout_destination_owners(
        db,
        provider=provider,
        lookup_hash=lookup_hash,
    )
    if owner_count < MAX_PAYOUT_DESTINATION_OWNERS:
        return owner_count

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="payout_account_share_refused",
            target_type="payout_account",
            target_id=None,
            metadata={
                "provider": provider,
                "owner_count": owner_count,
                **owner_ref,
            },
        )
    logger.bind(
        module="financials",
        action="onboard_payout_account",
        user_id=actor_id,
    ).warning("payout_account_share_refused", provider=provider)
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=(
            "This bank account already receives payouts for several accounts. "
            "Contact support to use it here as well."
        ),
    )


async def _audit_shared_payout_destination(
    db: AsyncSession,
    *,
    actor_id: UUID,
    payout_account: PayoutAccount,
    owner_count: int,
) -> None:
    """Record that a bank account now collects for more than one owner.

    Written inside the registering transaction so the record cannot outlive a
    rolled-back account. Admin review reads this rather than the payout table,
    which is why the owner count travels with it.
    """
    await write_audit(
        db=db,
        actor_id=actor_id,
        action="payout_account_shared",
        target_type="payout_account",
        target_id=payout_account.id,
        metadata={
            "provider": payout_account.provider,
            "owner_count": owner_count,
            "user_id": str(payout_account.user_id) if payout_account.user_id else None,
            "org_id": str(payout_account.org_id) if payout_account.org_id else None,
        },
    )


async def create_payment_method_setup(
    db: AsyncSession,
    operator: User,
) -> PaymentMethodSetupResponse:
    """Create/reuse a Stripe Customer and return a SetupIntent client secret.

    The route requires an open step-up window; no factor is checked here.
    """
    operator_id = operator.id
    customer_id = operator.stripe_customer_id

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
        # The rollback expired ``operator``; reload the row inside this
        # transaction rather than lazy-loading from the expired instance.
        operator_row = await db.get(User, operator_id, with_for_update=True)
        if operator_row is not None and operator_row.stripe_customer_id is None:
            operator_row.stripe_customer_id = customer_id
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

    framework = await db.get(Framework, transaction.ref_id)
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    del framework
    invoice = await financials_invoices.issue_purchase_invoice_for_transaction(
        db,
        transaction=transaction,
    )
    await db.commit()

    key = invoice.s3_key
    settings = get_settings()
    if s3.storage.object_exists(settings.s3_reports_bucket, key):
        invoice_url = s3.storage.presigned_get(
            settings.s3_reports_bucket,
            key,
            INVOICE_URL_TTL_SECONDS,
            download_name=f"{invoice.invoice_number}.pdf",
        )
        # Handed back as data, not as a redirect: the caller authenticates with
        # the Authorization header and navigates to S3 itself, so no credential
        # ever rides in a URL.
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
            content=DownloadUrlResponse(download_url=invoice_url).model_dump(
                mode="json"
            ),
        )

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


async def _load_org_purchase(
    db: AsyncSession,
    *,
    org_id: UUID,
    transaction_id: UUID,
) -> Transaction:
    """Load an org-owned Framework purchase transaction."""
    transaction = await db.scalar(
        select(Transaction)
        .where(
            Transaction.id == transaction_id,
            Transaction.payer_org_id == org_id,
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


async def get_org_framework_purchase_invoice(
    db: AsyncSession,
    *,
    org_id: UUID,
    transaction_id: UUID,
) -> Response:
    """Return a generated org purchase invoice URL or queue its generation.

    Mirrors `get_framework_purchase_invoice` for an organization buyer: the
    invoice is issued lazily under the org identity (buyer name = org name,
    buyer email = the org billing contact, falling back to the owner) and
    delivered via a presigned URL once its PDF exists. The caller's admin
    access and org membership are enforced at the dependency layer; this method
    additionally guards that the purchase belongs to the organization.

    Args:
        db: Async SQLAlchemy session.
        org_id: UUID of the organization that made the purchase.
        transaction_id: UUID of the org-payer purchase transaction.

    Returns:
        A 200 response carrying a presigned invoice URL when the PDF exists,
        else a 202 response after queueing generation.

    Raises:
        HTTPException(404): Purchase, organization, or framework not found.
        HTTPException(409): Purchase is not settled, or the org has no billing
            contact to address the invoice to.
    """
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )
    transaction = await _load_org_purchase(
        db=db,
        org_id=org_id,
        transaction_id=transaction_id,
    )
    if transaction.status not in {"completed", "refunded"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invoice is only available for settled purchases.",
        )

    framework = await db.get(Framework, transaction.ref_id)
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    del org, framework
    try:
        invoice = await financials_invoices.issue_purchase_invoice_for_transaction(
            db,
            transaction=transaction,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    await db.commit()

    key = invoice.s3_key
    settings = get_settings()
    if s3.storage.object_exists(settings.s3_reports_bucket, key):
        invoice_url = s3.storage.presigned_get(
            settings.s3_reports_bucket,
            key,
            INVOICE_URL_TTL_SECONDS,
            download_name=f"{invoice.invoice_number}.pdf",
        )
        # Handed back as data, not as a redirect: the caller authenticates with
        # the Authorization header and navigates to S3 itself, so no credential
        # ever rides in a URL.
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
            content=DownloadUrlResponse(download_url=invoice_url).model_dump(
                mode="json"
            ),
        )

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
    operator: User,
    *,
    payment_method_id: str,
) -> PaymentMethodDeleteResponse:
    """Detach a provider-held payment method after the ownership check.

    The route requires an open step-up window; no factor is checked here.
    """
    operator_id = operator.id
    customer_id = operator.stripe_customer_id
    if customer_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment method not found.",
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
            user_id=operator_id,
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
            actor_id=operator_id,
            action="payment_method_removed",
            target_type="user",
            target_id=operator_id,
            metadata={
                "provider": "stripe",
                "payment_method_ref": _masked_provider_ref(detached_id),
            },
        )

    logger.bind(
        module="financials",
        action="delete_payment_method",
        user_id=operator_id,
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
    customer_id: str | None,
    payee_id: UUID | None,
    payee_org_id: UUID | None,
    framework_id: UUID,
    amount: Decimal,
    currency: str,
    provider: PaymentProvider = "stripe",
) -> UUID:
    """Persist the local purchase record before provider confirmation.

    Args:
        db: Async SQLAlchemy session.
        operator_id: UUID of the paying Operator.
        customer_id: Stripe customer to remember on the account, or None on
            rails that hold no reusable customer object.
        payee_id: Selling Contributor, when the seller is an individual.
        payee_org_id: Selling Organization, when the seller is an org.
        framework_id: Framework being licensed.
        amount: Charge amount in major units.
        currency: ISO 4217 code the charge is denominated in.
        provider: Rail settling the charge, stamped on the row so the webhook
            can refuse an event arriving on the wrong one.

    Returns:
        UUID of the newly created pending transaction.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        operator = await db.get(User, operator_id)
        if operator is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )
        if customer_id is not None and operator.stripe_customer_id is None:
            operator.stripe_customer_id = customer_id
        transaction = Transaction(
            payer_id=operator_id,
            payee_id=payee_id,
            payee_org_id=payee_org_id,
            amount=amount,
            currency=currency,
            platform_commission=Decimal("0.00"),
            net_amount=amount,
            transaction_type="purchase",
            status="pending",
            provider=provider,
            ref_id=framework_id,
            ref_type="framework",
        )
        db.add(transaction)
        await db.flush()
        transaction_id = transaction.id
    return transaction_id


async def _create_pending_org_purchase_transaction(
    db: AsyncSession,
    *,
    org_id: UUID,
    payee_id: UUID | None,
    payee_org_id: UUID | None,
    framework_id: UUID,
    amount: Decimal,
    currency: str,
    provider: PaymentProvider = "stripe",
) -> UUID:
    """Persist the local org-payer purchase record before provider confirmation.

    Sibling of `_create_pending_purchase_transaction` for organization
    checkout: stamps `payer_org_id` instead of `payer_id` and never touches a
    user's `stripe_customer_id` (the org Stripe customer is only created
    during payment-method setup, not lazily here).
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        transaction = Transaction(
            payer_id=None,
            payer_org_id=org_id,
            payee_id=payee_id,
            payee_org_id=payee_org_id,
            amount=amount,
            currency=currency,
            platform_commission=Decimal("0.00"),
            net_amount=amount,
            transaction_type="purchase",
            status="pending",
            provider=provider,
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
    provider: PaymentProvider = "stripe",
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
                "provider": provider,
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
    provider: PaymentProvider = "stripe",
) -> None:
    """Mark checkout failure without granting a License.

    For an organization purchase the owners and the initiating member are told
    after commit (Slice C ``org_purchase_failed``); the notice never affects
    the status change itself.
    """
    org_notice: dict[str, object] | None = None
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
                "provider": provider,
                "framework_id": str(framework_id),
                "license_type": license_type,
            },
        )
        if transaction.payer_org_id is not None:
            payer_org_id = transaction.payer_org_id
            org_notice = {
                "owner_ids": await org_notifications.org_owner_ids(db, payer_org_id),
                "initiator_id": operator_id,
                "org_id": payer_org_id,
                "org_name": await org_notifications.org_name(db, payer_org_id),
                "transaction_id": transaction.id,
                "framework_title": await db.scalar(
                    select(Framework.title).where(Framework.id == framework_id)
                )
                or "a Framework",
                "amount": transaction.amount,
                "currency": transaction.currency,
                "failure_reason": "The payment provider could not start checkout.",
            }
    if org_notice is not None:
        org_notifications.notify_org_purchase_failed(
            org_notice.pop("owner_ids"),  # type: ignore[arg-type]
            **org_notice,  # type: ignore[arg-type]
        )


def _purchase_callback_url(
    transaction_id: UUID,
    *,
    buyer_org_id: UUID | None = None,
) -> str:
    """Build the URL Paystack returns a Framework buyer to after payment.

    Paystack keeps the payer on its own success page when no callback URL is
    sent, so a buyer who has already paid never sees the License land and can
    pay a second time. The escrow itself settles from the webhook either way,
    so this is a stranded user rather than lost money.

    Args:
        transaction_id: Pending purchase transaction, echoed so the Library
            can confirm the specific purchase that just completed.
        buyer_org_id: Purchasing Organization, when the buyer is an org — its
            Library lives under the org workspace rather than at `/library`.

    Returns:
        Absolute URL on the frontend origin.
    """
    library_path = (
        f"/dashboard/organizations/{buyer_org_id}/operator/library"
        if buyer_org_id
        else "/library"
    )
    base = get_settings().frontend_base_url
    return f"{base}{library_path}?purchase={transaction_id}"


async def _start_paystack_purchase(
    db: AsyncSession,
    *,
    operator_id: UUID,
    operator_email: str,
    payee_id: UUID | None,
    payee_org_id: UUID | None,
    framework_id: UUID,
    license_type: str,
    amount: Decimal,
    currency: str,
) -> PurchaseResponse:
    """Book a pending Paystack purchase and return its hosted checkout URL.

    Paystack has no stored-payment-method equivalent, so there is no customer
    to create first: the transaction row is written, the charge is initialized,
    and the browser is sent to Paystack's own page to enter card details.

    Args:
        db: Async SQLAlchemy session.
        operator_id: UUID of the paying Operator.
        operator_email: Email Paystack sends the receipt to.
        payee_id: Selling Contributor, when the seller is an individual.
        payee_org_id: Selling Organization, when the seller is an org.
        framework_id: Framework being licensed.
        license_type: License tier being bought, echoed back by the webhook.
        amount: Charge amount in major units.
        currency: ISO 4217 code the charge is denominated in.

    Returns:
        The pending transaction id and the URL to redirect the browser to.

    Raises:
        HTTPException(502): Paystack could not initialize the charge. The
            pending transaction is marked failed first so it never strands.
    """
    transaction_id = await _create_pending_purchase_transaction(
        db=db,
        operator_id=operator_id,
        customer_id=None,
        payee_id=payee_id,
        payee_org_id=payee_org_id,
        framework_id=framework_id,
        amount=amount,
        currency=currency,
        provider="paystack",
    )

    try:
        initialized = await paystack.initialize_transaction(
            callback_url=_purchase_callback_url(transaction_id),
            email=operator_email,
            amount=amount,
            currency=currency,
            metadata={
                "transaction_id": str(transaction_id),
                "kind": "purchase",
                "framework_id": str(framework_id),
                "license_type": license_type,
            },
        )
    except PaystackProviderError as exc:
        await _mark_purchase_failed(
            db=db,
            operator_id=operator_id,
            transaction_id=transaction_id,
            framework_id=framework_id,
            license_type=license_type,
            provider="paystack",
        )
        logger.bind(
            module="financials",
            action="create_framework_purchase",
            user_id=operator_id,
            framework_id=framework_id,
            transaction_id=transaction_id,
        ).error("paystack_initialize_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    await _mark_purchase_initiated(
        db=db,
        operator_id=operator_id,
        transaction_id=transaction_id,
        provider_ref=initialized.reference,
        framework_id=framework_id,
        license_type=license_type,
        provider="paystack",
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
        provider="paystack",
        authorization_url=initialized.authorization_url,
    )


async def _start_paystack_org_purchase(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID,
    organization: Organization,
    payee_id: UUID | None,
    payee_org_id: UUID | None,
    framework_id: UUID,
    license_type: str,
    amount: Decimal,
    currency: str,
) -> PurchaseResponse:
    """Book a pending org Paystack purchase and return its hosted checkout URL.

    Org sibling of `_start_paystack_purchase`: the charge bills the org's
    billing email (falling back to the owner) and the metadata carries
    `payer_org_id` so the settlement webhook mints an org-owned License.

    Raises:
        HTTPException(409): The org has no billing contact to charge.
        HTTPException(502): Paystack could not initialize the charge. The
            pending transaction is marked failed first so it never strands.
    """
    # Resolved before any commit so the org row is still fresh in-session.
    try:
        billing_email = await financials_invoices.resolve_org_billing_email(
            db, organization
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    transaction_id = await _create_pending_org_purchase_transaction(
        db=db,
        org_id=org_id,
        payee_id=payee_id,
        payee_org_id=payee_org_id,
        framework_id=framework_id,
        amount=amount,
        currency=currency,
        provider="paystack",
    )

    try:
        initialized = await paystack.initialize_transaction(
            callback_url=_purchase_callback_url(
                transaction_id,
                buyer_org_id=org_id,
            ),
            email=billing_email,
            amount=amount,
            currency=currency,
            metadata={
                "transaction_id": str(transaction_id),
                "kind": "purchase",
                "framework_id": str(framework_id),
                "license_type": license_type,
                "payer_org_id": str(org_id),
            },
        )
    except PaystackProviderError as exc:
        await _mark_purchase_failed(
            db=db,
            operator_id=actor_id,
            transaction_id=transaction_id,
            framework_id=framework_id,
            license_type=license_type,
            provider="paystack",
        )
        logger.bind(
            module="financials",
            action="create_org_framework_purchase",
            user_id=actor_id,
            org_id=org_id,
            framework_id=framework_id,
            transaction_id=transaction_id,
        ).error("paystack_initialize_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    await _mark_purchase_initiated(
        db=db,
        operator_id=actor_id,
        transaction_id=transaction_id,
        provider_ref=initialized.reference,
        framework_id=framework_id,
        license_type=license_type,
        provider="paystack",
    )
    logger.bind(
        module="financials",
        action="create_org_framework_purchase",
        user_id=actor_id,
        org_id=org_id,
        framework_id=framework_id,
        transaction_id=transaction_id,
    ).info("org_purchase_initiated")
    return PurchaseResponse(
        transaction_id=transaction_id,
        provider="paystack",
        authorization_url=initialized.authorization_url,
    )


async def create_framework_purchase(
    db: AsyncSession,
    operator: User,
    *,
    framework_id: UUID,
    payload: PurchaseRequest,
) -> PurchaseResponse:
    """Create a pending transaction and provider checkout handoff.

    The payment rail is chosen from the payer's stated country: Nigerian
    payers settle on Paystack's hosted redirect flow, everyone else on a
    Stripe PaymentIntent confirmed in-page.
    """
    operator_id = operator.id
    operator_email = operator.email
    operator_display_name = operator.display_name
    customer_id = operator.stripe_customer_id

    framework = await db.scalar(
        select(Framework).where(
            Framework.id == framework_id,
            Framework.status == "published",
            Framework.deleted_at.is_(None),
        )
    )
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )

    from app.modules.frameworks.ownership import resolve_framework_seller

    seller = resolve_framework_seller(framework)
    if seller.kind == "user":
        contributor_id = seller.user_id
        assert contributor_id is not None
        contributor = await db.get(User, contributor_id)
        if contributor is None or contributor.suspended_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )
    else:
        contributor_id = None
        # Org seller parity with the individual suspension guard: a suspended
        # (admin trust action) or deactivated organization must not settle new
        # sales. Matches catalog visibility, which already hides such orgs.
        seller_org = await db.get(Organization, seller.org_id)
        if (
            seller_org is None
            or seller_org.suspended_at is not None
            or seller_org.deactivated_at is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )

        # Org frameworks have no single contributor id, so the individual
        # self-purchase guard below never matches. Block any member of the
        # selling org from buying its own Framework — same self-dealing and
        # metric-gaming concern as the personal "cannot buy your own" rule.
        buyer_is_seller_member = await db.scalar(
            select(OrgMember.id)
            .where(
                OrgMember.org_id == seller.org_id,
                OrgMember.user_id == operator_id,
            )
            .limit(1)
        )
        if buyer_is_seller_member is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You cannot purchase your own organization's Framework.",
            )

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

    amount = _normalise_money(resolve_license_price(framework, payload.license_type))
    currency = framework.currency.upper()
    if currency != platform_currency():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Only {platform_currency()} purchases are supported.",
        )

    provider = select_provider(user_country=payload.country, currency=currency)
    if provider == "paystack":
        return await _start_paystack_purchase(
            db=db,
            operator_id=operator_id,
            operator_email=operator_email,
            payee_id=contributor_id,
            payee_org_id=seller.org_id,
            framework_id=framework_id,
            license_type=payload.license_type,
            amount=amount,
            currency=currency,
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
        payee_id=contributor_id,
        payee_org_id=seller.org_id,
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


async def create_org_framework_purchase(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor: User,
    framework_id: UUID,
    payload: PurchaseRequest,
) -> PurchaseResponse:
    """Create a pending org-payer transaction and Stripe PaymentIntent for checkout.

    Mirrors `create_framework_purchase` but the purchase is made on behalf of
    an Organization: the org's pre-existing Stripe customer pays, and the
    resulting License (minted by the webhook branch on payment success) is
    owned by the Organization (`licensee_org_id`), not `actor`.

    Args:
        db: Async SQLAlchemy session.
        org_id: UUID of the purchasing organization. Must hold an active
            Operator capability and a Stripe customer already on file.
        actor: Authenticated org admin/owner initiating checkout. Used only
            to attribute the `purchase_initiated` audit entry.
        framework_id: UUID of the Framework to purchase.
        payload: Requested license type.

    Returns:
        PaymentIntent data needed by the browser to complete checkout.

    Raises:
        HTTPException(403): Operator capability is not active for the org.
        HTTPException(404): Organization or Framework not found/unavailable.
        HTTPException(402): Organization has no payment method on file.
        HTTPException(422): Self-deal, unsupported license type, or a
            non-USD Framework price.
        HTTPException(409): Organization already holds an active License.
        HTTPException(502): Stripe PaymentIntent creation failed.
    """
    # Captured before any pending-transaction helper rolls back/restarts the
    # shared session, which would expire `actor` and require a lazy reload.
    actor_id = actor.id

    if not await operator_capability_active(db, org_id=org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(
                "capability_suspended",
                "The organization's Operator capability is not active.",
            ),
        )

    framework = await db.scalar(
        select(Framework).where(
            Framework.id == framework_id,
            Framework.status == "published",
            Framework.deleted_at.is_(None),
        )
    )
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )

    from app.modules.frameworks.ownership import resolve_framework_seller

    seller = resolve_framework_seller(framework)
    if seller.kind == "org":
        # Self-deal guard runs before any charge or transaction row exists.
        if seller.org_id == org_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="self_deal_conflict",
            )
        contributor_id = None
        seller_org = await db.get(Organization, seller.org_id)
        if (
            seller_org is None
            or seller_org.suspended_at is not None
            or seller_org.deactivated_at is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )
    else:
        contributor_id = seller.user_id
        assert contributor_id is not None
        contributor = await db.get(User, contributor_id)
        if contributor is None or contributor.suspended_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )

    existing_license_id = await db.scalar(
        select(License.id)
        .where(
            License.framework_id == framework_id,
            License.licensee_org_id == org_id,
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

    amount = _normalise_money(resolve_license_price(framework, payload.license_type))
    currency = framework.currency.upper()
    if currency != platform_currency():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Only {platform_currency()} purchases are supported.",
        )

    organization = await db.get(Organization, org_id)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )

    provider = select_provider(user_country=payload.country, currency=currency)
    if provider == "paystack":
        # Paystack has no stored-payment-method concept, so no org Stripe
        # customer is required on this rail: the charge is initialized against
        # the org's billing contact and the browser is redirected.
        return await _start_paystack_org_purchase(
            db=db,
            org_id=org_id,
            actor_id=actor_id,
            organization=organization,
            payee_id=contributor_id,
            payee_org_id=seller.org_id,
            framework_id=framework_id,
            license_type=payload.license_type,
            amount=amount,
            currency=currency,
        )

    customer_id = organization.stripe_customer_id
    if customer_id is None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Organization has no payment method on file.",
        )

    transaction_id = await _create_pending_org_purchase_transaction(
        db=db,
        org_id=org_id,
        payee_id=contributor_id,
        payee_org_id=seller.org_id,
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
                "payer_org_id": str(org_id),
            },
            idempotency_key=f"purchase:{transaction_id}",
        )
    except StripeProviderError as exc:
        await _mark_purchase_failed(
            db=db,
            operator_id=actor_id,
            transaction_id=transaction_id,
            framework_id=framework_id,
            license_type=payload.license_type,
        )
        logger.bind(
            module="financials",
            action="create_org_framework_purchase",
            user_id=actor_id,
            org_id=org_id,
            framework_id=framework_id,
            transaction_id=transaction_id,
        ).error("stripe_payment_intent_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    await _mark_purchase_initiated(
        db=db,
        operator_id=actor_id,
        transaction_id=transaction_id,
        provider_ref=payment_intent.id,
        framework_id=framework_id,
        license_type=payload.license_type,
    )
    logger.bind(
        module="financials",
        action="create_org_framework_purchase",
        user_id=actor_id,
        org_id=org_id,
        framework_id=framework_id,
        transaction_id=transaction_id,
    ).info("org_purchase_initiated")
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
    if transaction.provider_ref is None:
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
    if transaction.provider_ref is None:
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
    commission.voided_at = datetime.now(UTC)
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


async def _create_provider_refund(
    transaction: Transaction,
    *,
    action: str,
    operator_id: UUID,
) -> tuple[str, str]:
    """Refund a purchase on the rail it was paid on and return the refund id.

    The two rails differ in more than the call shape. Stripe refunds a
    PaymentIntent and reports a terminal status straight away; Paystack
    refunds a charge reference and only accepts the request here, settling it
    later and confirming through a `refund.processed` webhook. The caller
    treats both as refunded immediately — see `refund_framework_purchase` for
    why, and `_handle_paystack_refund_failed` for the reversal when Paystack
    ultimately declines it.

    Args:
        transaction: The completed purchase being refunded. Its `provider_ref`
            must be set, which the loaders above have already checked.
        action: Log action tag, so collection and single refunds stay distinct.
        operator_id: The requesting Operator, for log context.

    Returns:
        The provider's refund identifier.

    Raises:
        HTTPException(502): The payment provider rejected or could not be
            reached. No local state has changed at this point.
    """
    assert transaction.provider_ref is not None
    amount = _normalise_money(transaction.amount)
    currency = transaction.currency.upper()
    # Durable intent before the provider call: a crash between the provider
    # accepting the refund and our commit would otherwise leave money moved
    # with no local record. The intent sweeper reconciles orphans.
    intent_key = await refund_intents.record_refund_intent(
        transaction_id=transaction.id,
        charge_ref=transaction.provider_ref,
        rail=transaction.provider or "stripe",
        amount=amount,
        currency=currency,
        actor_id=operator_id,
    )
    try:
        if transaction.provider == "paystack":
            paystack_refund = await paystack.refund_transaction(
                transaction_reference=transaction.provider_ref,
                amount=amount,
                currency=currency,
            )
            return paystack_refund.id, intent_key
        stripe_refund = await stripe.create_refund(
            payment_intent_id=transaction.provider_ref,
            amount=amount,
            currency=currency,
            idempotency_key=f"refund:{transaction.id}",
        )
        return stripe_refund.id, intent_key
    except (StripeProviderError, PaystackProviderError) as exc:
        logger.bind(
            module="financials",
            action=action,
            user_id=operator_id,
            transaction_id=transaction.id,
        ).error(
            "provider_refund_failed",
            provider=transaction.provider,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc


async def _record_refund_requested(
    db: AsyncSession,
    *,
    transaction: Transaction,
    refund_id: str,
    operator_id: UUID,
    intent_key: str | None = None,
) -> None:
    """Append the refund to the money ledger, carrying the provider's id.

    Written for both rails so every refund appears in the ledger, but it is the
    Paystack case the id matters for: their refunds settle asynchronously, and
    `GET /refund/{id}` is the only way to ask what became of one. The audit log
    masks that id, so this row is the sole place it survives in full.

    The event is `refund_requested` rather than `refunded` because the money
    has not moved yet. The settlement webhook appends the outcome.

    Args:
        db: Async session already inside the caller's transaction.
        transaction: The purchase being refunded, already marked refunded.
        refund_id: The provider's identifier for the refund it accepted.
        operator_id: The Operator who requested it.
    """
    await record_financial_event(
        db,
        entity_type="transaction",
        entity_id=transaction.id,
        event_type="refund_requested",
        from_status="completed",
        to_status="refunded",
        amount=_normalise_money(transaction.amount),
        currency=transaction.currency,
        provider=transaction.provider,
        provider_ref=refund_id,
        actor_id=operator_id,
        metadata={"intent_key": intent_key} if intent_key else None,
    )


async def refund_framework_purchase(
    db: AsyncSession,
    operator: User,
    *,
    transaction_id: UUID,
) -> RefundResponse:
    """Refund an eligible Framework or Collection purchase.

    Works on both rails. The purchase is marked refunded and every licence it
    minted is revoked as soon as the provider accepts the refund, which on
    Paystack is before the money has actually moved. That ordering is
    deliberate: leaving access live during Paystack's settlement window would
    let the buyer download the artifacts and keep both them and the refund,
    and would leave the amount inside the Contributor's payable balance where
    it could be withdrawn. If Paystack later declines the refund, the
    `refund.failed` webhook reverses both.

    Args:
        db: Async SQLAlchemy session.
        operator: The authenticated Operator, who must be the payer.
        transaction_id: The purchase to refund.

    Returns:
        The refund acknowledgement, carrying the rail it settled on.

    Raises:
        HTTPException(404): No such purchase for this Operator.
        HTTPException(409): The purchase is not in a refundable state, or an
            artifact download landed between the provider call and the write.
        HTTPException(422): The refund window has expired, or an artifact has
            already been downloaded.
        HTTPException(502): The payment provider could not be reached.
    """
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
            refund_id, intent_key = await _create_provider_refund(
                collection_transaction,
                action="refund_collection_purchase",
                operator_id=operator_id,
            )

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
                        "Refund provider call completed but a download was recorded."
                    ),
                )

            collection_transaction.status = "refunded"
            await _record_refund_requested(
                db,
                transaction=collection_transaction,
                refund_id=refund_id,
                operator_id=operator_id,
                intent_key=intent_key,
            )
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
                    "provider": collection_transaction.provider,
                    "refund_ref": _masked_provider_ref(refund_id),
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
                provider=collection_transaction.provider,
                refund_id=refund_id,
                status="refunded",
            )

        transaction, license_row = await _load_refundable_purchase(
            db=db,
            operator_id=operator_id,
            transaction_id=transaction_id,
        )
        provider = transaction.provider
        refund_id, intent_key = await _create_provider_refund(
            transaction,
            action="refund_framework_purchase",
            operator_id=operator_id,
        )

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
        await _record_refund_requested(
            db,
            transaction=transaction,
            refund_id=refund_id,
            operator_id=operator_id,
            intent_key=intent_key,
        )
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
                "provider": provider,
                "refund_ref": _masked_provider_ref(refund_id),
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
        provider=provider,
        refund_id=refund_id,
        status="refunded",
    )


async def get_contributor_earnings(
    db: AsyncSession,
    contributor: User,
) -> EarningsResponse:
    """Return refund-safe Contributor earnings balances."""
    currency = platform_currency()
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


# ---------------------------------------------------------------------------
# Organization settlement, payout, and invoicing
#
# Organizations can now earn from contributor marketplace activity
# (Framework sales and released project Milestones) as well as attestation
# work. These helpers mirror the individual payout machinery keyed on
# ``transactions.payee_org_id``.
# ---------------------------------------------------------------------------


async def _sum_org_transactions(
    db: AsyncSession,
    *,
    org_id: UUID,
    currency: str,
    earning_class: str,
    before: datetime | None = None,
    after_or_at: datetime | None = None,
    net: bool = False,
) -> Decimal:
    """Return completed org earnings for one earning class, gross or net."""
    class_filter = earning_class_filter(earning_class)
    filters = [
        Transaction.payee_org_id == org_id,
        class_filter,
        Transaction.status == "completed",
        Transaction.currency == currency,
    ]
    if before is not None:
        filters.append(Transaction.created_at < before)
    if after_or_at is not None:
        filters.append(Transaction.created_at >= after_or_at)
    column = Transaction.net_amount if net else Transaction.amount
    value = await db.scalar(select(func.coalesce(func.sum(column), 0)).where(*filters))
    return _normalise_money(Decimal(value or "0"))


async def _claimed_org_payouts(
    db: AsyncSession,
    *,
    org_id: UUID,
    currency: str,
) -> Decimal:
    """Return net payout amounts an org has already claimed."""
    value = await db.scalar(
        select(func.coalesce(func.sum(Payout.net_amount), 0)).where(
            Payout.org_id == org_id,
            Payout.currency == currency,
            Payout.status.in_(PAYOUT_CLAIM_STATUSES),
        )
    )
    return _normalise_money(Decimal(value or "0"))


async def _available_org_payout_balance(
    db: AsyncSession,
    *,
    org_id: UUID,
    currency: str,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Return gross, pending, available, claimed, and commission for an org.

    Net values sum each sale's stamped `net_amount`, mirroring the individual
    balance: the rate in force when a sale settled is what the org withdraws
    at, and a later configured-rate change reprices nothing.
    """
    refund_window_hours = await _refund_window_hours(db)
    cutoff = datetime.now(UTC) - timedelta(hours=refund_window_hours)
    marketplace_gross = await _sum_org_transactions(
        db,
        org_id=org_id,
        currency=currency,
        earning_class=_MARKETPLACE_EARNING_CLASS,
    )
    marketplace_pending = await _sum_org_transactions(
        db,
        org_id=org_id,
        currency=currency,
        earning_class=_MARKETPLACE_EARNING_CLASS,
        after_or_at=cutoff,
    )
    marketplace_cleared_gross = await _sum_org_transactions(
        db,
        org_id=org_id,
        currency=currency,
        earning_class=_MARKETPLACE_EARNING_CLASS,
        before=cutoff,
    )
    attestation_gross = await _sum_org_transactions(
        db,
        org_id=org_id,
        currency=currency,
        earning_class=_ATTESTATION_EARNING_CLASS,
    )
    marketplace_cleared_net = await _sum_org_transactions(
        db,
        org_id=org_id,
        currency=currency,
        earning_class=_MARKETPLACE_EARNING_CLASS,
        before=cutoff,
        net=True,
    )
    attestation_cleared_net = await _sum_org_transactions(
        db,
        org_id=org_id,
        currency=currency,
        earning_class=_ATTESTATION_EARNING_CLASS,
        net=True,
    )
    claimed = await _claimed_org_payouts(db, org_id=org_id, currency=currency)
    total_cleared_gross = marketplace_cleared_gross + attestation_gross
    total_cleared_net = marketplace_cleared_net + attestation_cleared_net
    available = max(_normalise_money(total_cleared_net - claimed), Decimal("0.00"))
    gross_revenue = marketplace_gross + attestation_gross
    pending_clearance = marketplace_pending
    commission_rate = _blended_commission_rate(total_cleared_gross, total_cleared_net)
    return gross_revenue, pending_clearance, available, claimed, commission_rate


async def _lock_org_financials(db: AsyncSession, *, org_id: UUID) -> None:
    """Serialize payout balance mutations for one organization."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"payout:org:{org_id}"},
    )


async def _has_active_org_payout_account(db: AsyncSession, org_id: UUID) -> bool:
    """Return whether the org has any non-deleted payout account."""
    existing_id = await db.scalar(
        select(PayoutAccount.id)
        .where(
            PayoutAccount.org_id == org_id,
            PayoutAccount.deleted_at.is_(None),
        )
        .limit(1)
    )
    return existing_id is not None


async def get_org_earnings(
    db: AsyncSession,
    *,
    org_id: UUID,
) -> OrgEarningsResponse:
    """Return an organization's released earnings and payout eligibility.

    The eligibility checklist is computed by `_org_payout_blockers`, the same
    helper `request_org_payout` refuses on, so the checklist the owner sees
    cannot drift from what the request path enforces.
    """
    currency = platform_currency()
    (
        gross_revenue,
        pending_clearance,
        available,
        _,
        commission_rate,
    ) = await _available_org_payout_balance(db, org_id=org_id, currency=currency)
    reasons = await _org_payout_blockers(
        db, org_id=org_id, currency=currency, available=available
    )
    return OrgEarningsResponse(
        currency=currency,
        gross_revenue=gross_revenue,
        pending_clearance=pending_clearance,
        available_balance=available,
        commission_rate=commission_rate,
        minimum_payout=await _minimum_payout(db, currency),
        payout_eligibility=PayoutEligibility(
            eligible=not reasons,
            reasons=reasons,
        ),
    )


async def list_org_payouts(
    db: AsyncSession,
    *,
    org_id: UUID,
    page: int,
    page_size: int,
) -> OrgPayoutHistoryResponse:
    """Return one organization's payouts, newest first, with failure reasons.

    Read-only. The failure reason is the latest normalized ledger message for
    a failed payout; the payout row itself stores none.
    """
    total = int(
        await db.scalar(select(func.count(Payout.id)).where(Payout.org_id == org_id))
        or 0
    )
    rows = (
        await db.execute(
            select(Payout, PayoutAccount.provider)
            .join(PayoutAccount, PayoutAccount.id == Payout.payout_account_id)
            .where(Payout.org_id == org_id)
            .order_by(Payout.initiated_at.desc(), Payout.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    failed_ids = [payout.id for payout, _ in rows if payout.status == "failed"]
    reasons = await _latest_failure_reasons(
        db, entity_type="payout", event_type="payout_failed", entity_ids=failed_ids
    )
    return OrgPayoutHistoryResponse(
        payouts=[
            OrgPayoutHistoryItem(
                id=payout.id,
                amount=payout.net_amount,
                currency=payout.currency,
                status=payout.status,
                provider=provider,
                requested_at=payout.initiated_at,
                completed_at=payout.completed_at,
                failure_reason=reasons.get(payout.id),
            )
            for payout, provider in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


async def list_org_purchases(
    db: AsyncSession,
    *,
    org_id: UUID,
    status_filter: str | None,
    limit: int,
) -> OrgPurchasesResponse:
    """Return the organization's Framework purchases, newest first.

    Read-only billing view. ``status_filter`` narrows to one transaction
    status (``failed`` for the failed-purchases list); failure reasons come
    from the normalized ledger entry the settlement webhook wrote.
    """
    query = (
        select(Transaction, Framework.title)
        .outerjoin(Framework, Framework.id == Transaction.ref_id)
        .where(
            Transaction.payer_org_id == org_id,
            Transaction.transaction_type == "purchase",
            Transaction.ref_type == "framework",
        )
    )
    if status_filter is not None:
        query = query.where(Transaction.status == status_filter)
    rows = (
        await db.execute(
            query.order_by(Transaction.created_at.desc(), Transaction.id.desc()).limit(
                limit
            )
        )
    ).all()
    failed_ids = [row.id for row, _ in rows if row.status == "failed"]
    reasons = await _latest_failure_reasons(
        db,
        entity_type="transaction",
        event_type="purchase_failed",
        entity_ids=failed_ids,
    )
    return OrgPurchasesResponse(
        purchases=[
            OrgPurchaseListItem(
                transaction_id=row.id,
                framework_id=row.ref_id,
                framework_title=title,
                amount=row.amount,
                currency=row.currency,
                status=row.status,
                failure_reason=reasons.get(row.id),
                created_at=row.created_at,
            )
            for row, title in rows
        ]
    )


async def _latest_failure_reasons(
    db: AsyncSession,
    *,
    entity_type: str,
    event_type: str,
    entity_ids: list[UUID],
) -> dict[UUID, str]:
    """Map each entity to its most recent ledger failure message, if any."""
    if not entity_ids:
        return {}
    events = (
        await db.execute(
            select(FinancialEvent.entity_id, FinancialEvent.reason_message)
            .where(
                FinancialEvent.entity_type == entity_type,
                FinancialEvent.event_type == event_type,
                FinancialEvent.entity_id.in_(entity_ids),
                FinancialEvent.reason_message.is_not(None),
            )
            .order_by(FinancialEvent.occurred_at.asc())
        )
    ).all()
    # Ascending order lets the latest message overwrite earlier ones.
    return {entity_id: message for entity_id, message in events}


async def list_org_invoices(
    db: AsyncSession,
    *,
    org_id: UUID,
) -> OrgInvoicesResponse:
    """List issued invoices for an organization's settled work.

    PII rule: only non-sensitive invoice metadata is returned — no tax data or
    payout account details.
    """
    from app.modules.attestation.models import Attestation

    org_attestation_ids = select(Attestation.id).where(
        Attestation.attestor_org_id == org_id
    )
    # Sales: the org earned (attestation, or a transaction it was paid for).
    # Purchases: the org paid (a purchase transaction with payer_org_id).
    org_sale_transaction_ids = select(Transaction.id).where(
        Transaction.payee_org_id == org_id
    )
    org_purchase_transaction_ids = {
        row
        for row in (
            await db.scalars(
                select(Transaction.id).where(
                    Transaction.payer_org_id == org_id,
                    Transaction.transaction_type == "purchase",
                )
            )
        )
    }
    rows = (
        (
            await db.execute(
                select(Invoice)
                .where(
                    or_(
                        (
                            (Invoice.source_ref_type == "attestation")
                            & Invoice.source_ref_id.in_(org_attestation_ids)
                        ),
                        (
                            (Invoice.source_ref_type == "transaction")
                            & Invoice.source_ref_id.in_(org_sale_transaction_ids)
                        ),
                        (
                            (Invoice.source_ref_type == "transaction")
                            & Invoice.source_ref_id.in_(org_purchase_transaction_ids)
                        ),
                    )
                )
                .order_by(Invoice.issue_date.desc(), Invoice.id)
            )
        )
        .scalars()
        .all()
    )
    return OrgInvoicesResponse(
        invoices=[
            OrgInvoiceListItem(
                id=invoice.id,
                invoice_number=invoice.invoice_number,
                doc_type=invoice.doc_type,
                issue_date=invoice.issue_date,
                currency=invoice.currency,
                total=invoice.total,
                source_ref_type=invoice.source_ref_type,
                source_ref_id=invoice.source_ref_id,
                direction=(
                    "purchase"
                    if invoice.source_ref_id in org_purchase_transaction_ids
                    else "sales"
                ),
            )
            for invoice in rows
        ]
    )


async def _onboard_paystack_org_payout_account(
    db: AsyncSession,
    *,
    org_id: UUID,
    org_name: str,
    actor_id: UUID,
    payload: OrgPayoutAccountOnboardRequest,
) -> PayoutAccountOnboardResponse:
    """Register an organization's Nigerian bank account as a transfer recipient.

    Mirrors the individual rail in `_onboard_paystack_payout_account`: Paystack
    resolves the account against the bank while creating the recipient, so a
    successful call is itself the verification and the account is usable with
    no hosted onboarding step to wait on.

    The recipient is named for the organization rather than the acting member,
    because the bank account belongs to the org and a member can leave it.

    Args:
        db: Async SQLAlchemy session.
        org_id: Organization that will own the payout account.
        org_name: Organization name, registered as the recipient name.
        actor_id: Owner or admin performing the onboarding, for the audit row.
        payload: Onboarding request carrying `account_number` and `bank_code`.

    Returns:
        The stored payout account plus the bank-confirmed account name.

    Raises:
        HTTPException(502): Paystack rejected the account or was unreachable.
        HTTPException(409): A concurrent request already registered it.
    """
    existing_account = await db.scalar(
        select(PayoutAccount).where(
            PayoutAccount.org_id == org_id,
            PayoutAccount.provider == "paystack",
            PayoutAccount.deleted_at.is_(None),
        )
    )
    if existing_account is not None:
        logger.bind(
            module="financials",
            action="onboard_org_payout_account",
            org_id=org_id,
        ).info("payout_account_onboard_reused", provider="paystack")
        return PayoutAccountOnboardResponse(
            provider="paystack",
            onboarding_url=None,
            payout_account=_payout_account_response(existing_account),
        )

    # Narrowed by the request validator, which rejects a Paystack payload
    # missing either field before it can reach the provider.
    assert payload.account_number is not None
    assert payload.bank_code is not None

    try:
        recipient = await paystack.create_transfer_recipient(
            name=org_name,
            account_number=payload.account_number,
            bank_code=payload.bank_code,
            currency=platform_currency(),
        )
    except PaystackProviderError as exc:
        logger.bind(
            module="financials",
            action="onboard_org_payout_account",
            org_id=org_id,
        ).error("payout_account_provider_failed: {error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payout provider is unavailable.",
        ) from exc

    # Only after the provider call: the recipient code is what identifies the
    # bank account, and the same NUBAN always resolves to the same code.
    lookup_hash = hash_payout_provider_account_id(recipient.recipient_code)
    shared_with = await _guard_payout_destination_sharing(
        db,
        provider="paystack",
        lookup_hash=lookup_hash,
        actor_id=actor_id,
        owner_ref={"org_id": str(org_id)},
    )

    if db.in_transaction():
        await db.rollback()
    try:
        async with db.begin():
            payout_account = PayoutAccount(
                org_id=org_id,
                provider="paystack",
                provider_account_id=encrypt_payout_provider_account_id(
                    recipient.recipient_code
                ),
                provider_account_lookup_hash=lookup_hash,
                account_type="nuban",
                is_default=not await _has_active_org_payout_account(db, org_id),
                verified_at=datetime.now(UTC),
            )
            db.add(payout_account)
            await db.flush()
            await write_audit(
                db=db,
                actor_id=actor_id,
                action="payout_account_onboarded",
                target_type="payout_account",
                target_id=payout_account.id,
                metadata={
                    "provider": "paystack",
                    "account_type": "nuban",
                    "org_id": str(org_id),
                    "provider_account_ref": _masked_provider_ref(
                        recipient.recipient_code
                    ),
                    "bank_code": payload.bank_code,
                },
            )
            if shared_with:
                await _audit_shared_payout_destination(
                    db,
                    actor_id=actor_id,
                    payout_account=payout_account,
                    owner_count=shared_with + 1,
                )
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payout account already exists.",
        ) from exc

    logger.bind(
        module="financials",
        action="onboard_org_payout_account",
        org_id=org_id,
    ).info("payout_account_onboarded", provider="paystack")
    return PayoutAccountOnboardResponse(
        provider="paystack",
        onboarding_url=None,
        payout_account=_payout_account_response(payout_account),
        account_name=recipient.account_name,
    )


async def onboard_org_payout_account(
    db: AsyncSession,
    *,
    org: Organization,
    actor: User,
    payload: OrgPayoutAccountOnboardRequest,
) -> PayoutAccountOnboardResponse:
    """Create a provider-held payout destination owned by an organization.

    Provider routing follows the org's registered ``country``, and a provider
    that disagrees with the routing is refused rather than honoured: a Nigerian
    bank account registered against Stripe Connect could never be paid.

    Args:
        db: Async SQLAlchemy session.
        org: The organization the payout account will belong to.
        actor: The owner or admin performing the onboarding.
        payload: Onboarding request naming the provider and its rail's fields.

    Returns:
        The stored payout account and, on the Stripe rail, a hosted onboarding
        URL to redirect to.

    Raises:
        HTTPException(422): The requested provider does not settle that country.
        HTTPException(502): The payout provider rejected the request.
    """
    # Capture identity fields up front: the transaction below rolls back the
    # session, expiring the dependency-loaded ``org``/``actor`` instances and
    # turning later attribute access into a sync-context lazy refresh.
    org_id = org.id
    org_country = org.country
    org_name = org.name
    actor_id = actor.id
    actor_email = actor.email
    provider = select_provider(
        user_country=org_country,
        currency=platform_currency(),
    )
    if provider != payload.provider:
        logger.bind(
            module="financials",
            action="onboard_org_payout_account",
            user_id=actor_id,
            org_id=org_id,
        ).warning(
            "payout_provider_mismatch",
            requested=payload.provider,
            routed=provider,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Payout accounts for {org_country} settle on {provider}.",
        )
    if provider == "paystack":
        return await _onboard_paystack_org_payout_account(
            db,
            org_id=org_id,
            org_name=org_name,
            actor_id=actor_id,
            payload=payload,
        )

    # Narrowed by the request validator, which requires both URLs on this rail.
    assert payload.refresh_url is not None
    assert payload.return_url is not None

    existing_account = await db.scalar(
        select(PayoutAccount).where(
            PayoutAccount.org_id == org_id,
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
                action="onboard_org_payout_account",
                org_id=org_id,
            ).error("payout_account_provider_failed: {error}", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Payout provider is unavailable.",
            ) from exc
        return PayoutAccountOnboardResponse(
            provider=payload.provider,
            onboarding_url=onboarding_url,
            payout_account=_payout_account_response(existing_account),
        )

    try:
        stripe_account = await stripe.create_express_account(
            email=actor_email,
            country=org_country,
        )
        account_link = await stripe.create_account_link(
            account_id=stripe_account.id,
            refresh_url=payload.refresh_url,
            return_url=payload.return_url,
        )
        provider_account_id = stripe_account.id
        onboarding_url = account_link.url
    except StripeProviderError as exc:
        logger.bind(
            module="financials",
            action="onboard_org_payout_account",
            org_id=org_id,
        ).error("payout_account_provider_failed: {error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payout provider is unavailable.",
        ) from exc

    if db.in_transaction():
        await db.rollback()
    try:
        async with db.begin():
            payout_account = PayoutAccount(
                org_id=org_id,
                provider=payload.provider,
                provider_account_id=encrypt_payout_provider_account_id(
                    provider_account_id
                ),
                provider_account_lookup_hash=hash_payout_provider_account_id(
                    provider_account_id
                ),
                account_type="express",
                is_default=not await _has_active_org_payout_account(db, org_id),
            )
            db.add(payout_account)
            await db.flush()
            await write_audit(
                db=db,
                actor_id=actor_id,
                action="payout_account_onboarded",
                target_type="payout_account",
                target_id=payout_account.id,
                metadata={
                    "org_id": str(org_id),
                    "provider": payload.provider,
                    "account_type": "express",
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
        action="onboard_org_payout_account",
        org_id=org_id,
        user_id=actor_id,
    ).info("payout_account_onboarded")
    return PayoutAccountOnboardResponse(
        provider=payload.provider,
        onboarding_url=onboarding_url,
        payout_account=_payout_account_response(payout_account),
    )


async def replace_org_payout_account(
    db: AsyncSession,
    *,
    org: Organization,
    actor: User,
    payout_account_id: UUID,
    payload: OrgPayoutAccountOnboardRequest,
) -> PayoutAccountOnboardResponse:
    """Swap an organization's payout destination for a newly registered one.

    Registering and retiring happen together rather than as a delete followed
    by an add. An approved attestor application points at a specific payout
    account, and the approval gate reads that column: removing the account on
    its own would leave the organization approved but unpayable, with a
    checklist still reporting a linked account. Anything pointing at the old
    account is moved to the new one inside the same transaction.

    Stripe Connect is refused deliberately. The bank details behind a Connect
    account live at Stripe, so replacing them is done there — minting a second
    Connect account here would leave the organization with an unverified
    destination and no way back to the verified one.

    Args:
        db: Async SQLAlchemy session.
        org: Organization that owns the account being replaced.
        actor: Owner performing the replacement, for the audit row.
        payout_account_id: The destination to retire.
        payload: Bank details for the replacement destination.

    Returns:
        The newly registered payout account and its bank-confirmed name.

    Raises:
        HTTPException(404): The account is not this organization's, or is gone.
        HTTPException(409): A payout is already in flight for this org.
        HTTPException(422): The rail cannot replace an account in place.
        HTTPException(502): Paystack rejected the account or was unreachable.
    """
    org_id = org.id
    actor_id = actor.id
    log = logger.bind(
        module="financials",
        action="replace_org_payout_account",
        org_id=org_id,
        user_id=actor_id,
    )

    existing = await db.scalar(
        select(PayoutAccount).where(
            PayoutAccount.id == payout_account_id,
            PayoutAccount.org_id == org_id,
            PayoutAccount.deleted_at.is_(None),
        )
    )
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payout account not found.",
        )
    if existing.provider != "paystack":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Change the bank details for this account with Stripe instead. "
                "Stripe holds them, so they cannot be replaced here."
            ),
        )

    # Money already addressed to the old account must land before it is
    # retired; replacing mid-transfer would leave a payout referencing a
    # destination the organization can no longer see.
    in_flight = await db.scalar(
        select(Payout.id)
        .where(
            Payout.org_id == org_id,
            Payout.status.in_(("pending", "processing")),
        )
        .limit(1)
    )
    if in_flight is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A payout is still in progress. Replace this account once it "
                "has completed."
            ),
        )

    if payload.provider != "paystack":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="This organization settles through Paystack.",
        )
    # Narrowed by the request validator, which rejects a Paystack payload
    # missing either field before it can reach the provider.
    assert payload.account_number is not None
    assert payload.bank_code is not None

    try:
        recipient = await paystack.create_transfer_recipient(
            name=org.name,
            account_number=payload.account_number,
            bank_code=payload.bank_code,
            currency=platform_currency(),
        )
    except PaystackProviderError as exc:
        log.error("payout_account_provider_failed: {error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payout provider is unavailable.",
        ) from exc

    lookup_hash = hash_payout_provider_account_id(recipient.recipient_code)
    shared_with = await _guard_payout_destination_sharing(
        db,
        provider="paystack",
        lookup_hash=lookup_hash,
        actor_id=actor_id,
        owner_ref={"org_id": str(org_id)},
    )

    if db.in_transaction():
        await db.rollback()
    try:
        async with db.begin():
            retired = await db.scalar(
                select(PayoutAccount)
                .where(
                    PayoutAccount.id == payout_account_id,
                    PayoutAccount.org_id == org_id,
                    PayoutAccount.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if retired is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Payout account not found.",
                )
            retired.deleted_at = datetime.now(UTC)
            retired.is_default = False

            payout_account = PayoutAccount(
                org_id=org_id,
                provider="paystack",
                provider_account_id=encrypt_payout_provider_account_id(
                    recipient.recipient_code
                ),
                provider_account_lookup_hash=lookup_hash,
                account_type="nuban",
                is_default=True,
                # Paystack resolved the account against the bank to create the
                # recipient, so there is nothing further to confirm.
                verified_at=datetime.now(UTC),
            )
            db.add(payout_account)
            await db.flush()

            await db.execute(
                update(OrgAttestorApplication)
                .where(
                    OrgAttestorApplication.org_id == org_id,
                    OrgAttestorApplication.payout_account_id == payout_account_id,
                )
                .values(payout_account_id=payout_account.id)
            )

            await write_audit(
                db=db,
                actor_id=actor_id,
                action="payout_account_replaced",
                target_type="payout_account",
                target_id=payout_account.id,
                metadata={
                    "provider": "paystack",
                    "org_id": str(org_id),
                    "replaced_payout_account_id": str(payout_account_id),
                    "provider_account_ref": _masked_provider_ref(
                        recipient.recipient_code
                    ),
                    "bank_code": payload.bank_code,
                },
            )
            if shared_with:
                await _audit_shared_payout_destination(
                    db,
                    actor_id=actor_id,
                    payout_account=payout_account,
                    owner_count=shared_with + 1,
                )
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payout account already exists.",
        ) from exc

    log.info("payout_account_replaced", provider="paystack")
    return PayoutAccountOnboardResponse(
        provider="paystack",
        onboarding_url=None,
        payout_account=_payout_account_response(payout_account),
        account_name=recipient.account_name,
    )


async def _org_has_approved_attestor_application(
    db: AsyncSession,
    *,
    org_id: UUID,
) -> bool:
    """Return whether the org holds an approved attestor application (KYB gate)."""
    application_id = await db.scalar(
        select(OrgAttestorApplication.id)
        .where(
            OrgAttestorApplication.org_id == org_id,
            OrgAttestorApplication.status == "approved",
        )
        .limit(1)
    )
    return application_id is not None


async def _org_has_active_capability(
    db: AsyncSession,
    *,
    org_id: UUID,
    capability: str,
) -> bool:
    """Return whether the org capability is active."""
    capability_id = await db.scalar(
        select(OrgCapability.id)
        .where(
            OrgCapability.org_id == org_id,
            OrgCapability.capability == capability,
            OrgCapability.status == "active",
        )
        .limit(1)
    )
    return capability_id is not None


async def _org_has_legal_tax_document(
    db: AsyncSession,
    *,
    org_id: UUID,
) -> bool:
    """Return whether the org's shared legal profile has a tax document."""
    profile_id = await db.scalar(
        select(OrgLegalProfile.id)
        .where(
            OrgLegalProfile.org_id == org_id,
            OrgLegalProfile.tax_document_key.is_not(None),
        )
        .limit(1)
    )
    return profile_id is not None


# Blockers request_org_payout answers with 403, unchanged from before Slice C.
# Suspension and business verification are also in the checklist, but on the
# request path they are refused earlier by `require_org_role(..., verified=True)`
# with their own error codes, so the service does not re-decide them.
_ORG_PAYOUT_FORBIDDEN_CODES = frozenset(
    {"no_payout_capability", "tax_document_missing"}
)


async def _org_payout_blockers(
    db: AsyncSession,
    *,
    org_id: UUID,
    currency: str,
    available: Decimal | None,
) -> list[PayoutEligibilityReason]:
    """Return every unmet org payout condition, in checklist order.

    The single source of the org payout rules: `get_org_earnings` renders the
    result as the eligibility checklist and `request_org_payout` refuses on
    it, so the two cannot drift. Payout paths: an approved attestor
    application, or an active contributor capability plus a tax document on
    the shared legal profile.

    Args:
        db: Async session (inside the payout lock on the request path).
        org_id: Organization being checked.
        currency: Settlement currency, for the minimum payout message.
        available: Available net balance; ``None`` skips the minimum check
            (the request path checks the requested amount instead).

    Returns:
        Reasons with an app ``action_path`` where the owner can fix them; an
        empty list means the org can request a payout.
    """
    from app.modules.organizations.kyb_service import org_kyb_verified

    base = f"/dashboard/organizations/{org_id}"
    reasons: list[PayoutEligibilityReason] = []
    suspended_at = await db.scalar(
        select(Organization.suspended_at).where(Organization.id == org_id)
    )
    if suspended_at is not None:
        reasons.append(
            PayoutEligibilityReason(
                code="org_suspended",
                message="The organization is suspended, so payouts are paused.",
                action_path=None,
            )
        )
    if not await org_kyb_verified(db, org_id=org_id):
        reasons.append(
            PayoutEligibilityReason(
                code="kyb_not_verified",
                message="Complete business verification before requesting a payout.",
                action_path=f"{base}/verification",
            )
        )
    if not await _org_has_approved_attestor_application(db, org_id=org_id):
        if not await _org_has_active_capability(
            db, org_id=org_id, capability="contributor"
        ):
            reasons.append(
                PayoutEligibilityReason(
                    code="no_payout_capability",
                    message=(
                        "Payouts need an approved attestor application or an "
                        "active contributor capability."
                    ),
                    action_path=base,
                )
            )
        elif not await _org_has_legal_tax_document(db, org_id=org_id):
            reasons.append(
                PayoutEligibilityReason(
                    code="tax_document_missing",
                    message="Upload the organization's tax document.",
                    action_path=f"{base}/verification",
                )
            )
    in_flight = await db.scalar(
        select(Payout.id)
        .where(
            Payout.org_id == org_id,
            Payout.status.in_(("pending", "processing")),
        )
        .limit(1)
    )
    if in_flight is not None:
        reasons.append(
            PayoutEligibilityReason(
                code="payout_in_progress",
                message="A payout is already in progress for this organization.",
                action_path=None,
            )
        )
    verified_account = await db.scalar(
        select(PayoutAccount.id)
        .where(
            PayoutAccount.org_id == org_id,
            PayoutAccount.deleted_at.is_(None),
            PayoutAccount.verified_at.is_not(None),
        )
        .limit(1)
    )
    if verified_account is None:
        reasons.append(
            PayoutEligibilityReason(
                code="no_verified_payout_account",
                message="Add and verify a payout account.",
                action_path=f"{base}/financials",
            )
        )
    if available is not None:
        minimum = await _minimum_payout(db, currency)
        if available < minimum:
            from app.modules.organizations.notifications import format_money

            reasons.append(
                PayoutEligibilityReason(
                    code="below_minimum_payout",
                    message=(
                        "The available balance is below the minimum payout of "
                        f"{format_money(minimum, currency)} ({currency.upper()})."
                    ),
                    action_path=None,
                )
            )
    return reasons


async def request_org_payout(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor: User,
    payload: PayoutRequest,
) -> PayoutResponse:
    """Create a pending org payout and queue provider transfer processing.

    The route requires an open step-up window for the acting org owner
    (Decision 3: payout authority is owner-only). Gates: no payout already
    pending or processing for the org, the org owns a verified payout
    account, and it satisfies at least one eligible capability payout path.

    The in-flight and eligibility refusals come from `_org_payout_blockers`,
    the same helper that renders the earnings checklist. Owners are told after
    commit (``org_payout_requested``).

    Raises:
        HTTPException(403): The org is not payout-eligible.
        HTTPException(409): A payout for the org is already in flight.
    """
    actor_id = actor.id
    currency = payload.currency.upper()
    if currency != platform_currency():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Only {platform_currency()} payouts are supported.",
        )

    requested_net = _normalise_money(payload.amount)
    minimum = await _minimum_payout(db, currency)
    if requested_net < minimum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Minimum payout is {currency} {minimum}.",
        )

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await _lock_org_financials(db, org_id=org_id)
        # One payout in flight per org: a double-submit (or two owners
        # acting at once) must not draw the same balance down twice. The
        # account and amount blockers are checked below against the specific
        # request, which is stricter than the org-wide checklist.
        blockers = {
            reason.code
            for reason in await _org_payout_blockers(
                db, org_id=org_id, currency=currency, available=None
            )
        }
        if "payout_in_progress" in blockers:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A payout is already in progress for this organization.",
            )
        if blockers & _ORG_PAYOUT_FORBIDDEN_CODES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization is not payout-eligible.",
            )
        payout_account = await db.scalar(
            select(PayoutAccount)
            .where(
                PayoutAccount.id == payload.payout_account_id,
                PayoutAccount.org_id == org_id,
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

        _, _, available, _, commission_rate = await _available_org_payout_balance(
            db,
            org_id=org_id,
            currency=currency,
        )
        if requested_net > available:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Requested payout exceeds available balance.",
            )

        gross_drawdown = _normalise_money(
            requested_net / (Decimal("1") - commission_rate)
        )
        commission_deducted = _normalise_money(gross_drawdown - requested_net)
        payout = Payout(
            org_id=org_id,
            contributor_id=None,
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
            actor_id=actor_id,
            action="payout_requested",
            target_type="payout",
            target_id=payout.id,
            metadata={
                "org_id": str(org_id),
                "currency": currency,
                "net_amount": str(requested_net),
                "commission_deducted": str(commission_deducted),
            },
        )
        payout_id = payout.id
        owner_ids = await org_notifications.org_owner_ids(db, org_id)
        requested_org_name = await org_notifications.org_name(db, org_id)

    try:
        process_payout.delay(str(payout_id))
    except Exception as exc:
        logger.bind(
            module="financials",
            action="request_org_payout",
            org_id=org_id,
            payout_id=payout_id,
        ).error("payout_task_dispatch_failed", error=str(exc))

    logger.bind(
        module="financials",
        action="request_org_payout",
        org_id=org_id,
        user_id=actor_id,
        payout_id=payout_id,
    ).info("payout_requested")
    org_notifications.notify_org_payout_requested(
        owner_ids,
        org_id=org_id,
        org_name=requested_org_name,
        payout_id=payout_id,
        amount=requested_net,
        currency=currency,
    )
    refreshed = await db.get(Payout, payout_id)
    assert refreshed is not None
    return _payout_response(refreshed)


async def request_payout(
    db: AsyncSession,
    contributor: User,
    payload: PayoutRequest,
) -> PayoutResponse:
    """Create a pending payout request and queue provider transfer processing.

    The route requires an open step-up window; no factor is checked here.
    """
    contributor_id = contributor.id
    currency = payload.currency.upper()
    if currency != platform_currency():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Only {platform_currency()} payouts are supported.",
        )

    requested_net = _normalise_money(payload.amount)
    minimum = await _minimum_payout(db, currency)
    if requested_net < minimum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Minimum payout is {currency} {minimum}.",
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


# Paystack's country slug for the Nigerian bank list. Their `/bank` endpoint
# takes a lowercase country name, not an ISO code.
_PAYSTACK_BANK_COUNTRY = "nigeria"


async def list_payout_banks() -> PayoutBanksResponse:
    """List banks a Contributor can register a payout account at.

    Proxied from Paystack rather than served from a local table: bank codes
    change and new institutions appear, so a stale list would either reject a
    valid account or address a Contributor's money to the wrong bank.

    Returns:
        Banks available for payout onboarding on the Paystack rail.

    Raises:
        HTTPException(502): Paystack was unreachable or returned an
            unusable response. Failing closed is deliberate — an empty list
            would look like "no banks" and invite a guessed bank code.
    """
    try:
        banks = await paystack.list_banks(country=_PAYSTACK_BANK_COUNTRY)
    except PaystackProviderError as exc:
        logger.bind(module="financials", action="list_payout_banks").error(
            "payout_bank_list_failed: {error}", error=str(exc)
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Bank list is unavailable.",
        ) from exc
    return PayoutBanksResponse(
        banks=[PayoutBank(name=bank.name, code=bank.code) for bank in banks]
    )


async def _onboard_paystack_payout_account(
    db: AsyncSession,
    contributor: User,
    payload: PayoutAccountOnboardRequest,
) -> PayoutAccountOnboardResponse:
    """Register a Nigerian bank account as a Paystack transfer recipient.

    Paystack has no hosted onboarding to redirect to. The NUBAN details are
    submitted directly and Paystack resolves them against the bank while
    creating the recipient, so a successful call is itself the verification —
    unlike Stripe Connect, there is no `account.updated` webhook to wait for
    and the account is usable immediately.

    Args:
        db: Async SQLAlchemy session.
        contributor: The authenticated, KYC-verified Contributor.
        payload: Onboarding request carrying `account_number` and `bank_code`.

    Returns:
        The stored payout account plus the bank-confirmed account name.

    Raises:
        HTTPException(502): Paystack rejected the account or was unreachable.
        HTTPException(409): A concurrent request already registered it.
    """
    contributor_id = contributor.id

    # Re-onboarding returns the existing account untouched. There is no link to
    # refresh here, so calling the provider again would only risk a duplicate
    # recipient for the same person.
    existing_account = await db.scalar(
        select(PayoutAccount).where(
            PayoutAccount.user_id == contributor_id,
            PayoutAccount.provider == "paystack",
            PayoutAccount.deleted_at.is_(None),
        )
    )
    if existing_account is not None:
        logger.bind(
            module="financials",
            action="onboard_payout_account",
            user_id=contributor_id,
        ).info("payout_account_onboard_reused", provider="paystack")
        return PayoutAccountOnboardResponse(
            provider="paystack",
            onboarding_url=None,
            payout_account=_payout_account_response(existing_account),
        )

    # Narrowed by PayoutAccountOnboardRequest's model validator, which rejects a
    # Paystack payload missing either field before it can reach the provider.
    assert payload.account_number is not None
    assert payload.bank_code is not None

    try:
        recipient = await paystack.create_transfer_recipient(
            name=contributor.display_name,
            account_number=payload.account_number,
            bank_code=payload.bank_code,
            currency=platform_currency(),
        )
    except PaystackProviderError as exc:
        logger.bind(
            module="financials",
            action="onboard_payout_account",
            user_id=contributor_id,
        ).error("payout_account_provider_failed: {error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payout provider is unavailable.",
        ) from exc

    # Only after the provider call, because Paystack's recipient code is what
    # identifies the bank account: the same NUBAN always resolves to the same
    # code, and nothing before this point reveals which account was entered.
    lookup_hash = hash_payout_provider_account_id(recipient.recipient_code)
    shared_with = await _guard_payout_destination_sharing(
        db,
        provider="paystack",
        lookup_hash=lookup_hash,
        actor_id=contributor_id,
        owner_ref={"user_id": str(contributor_id)},
    )

    if db.in_transaction():
        await db.rollback()
    try:
        async with db.begin():
            payout_account = PayoutAccount(
                user_id=contributor_id,
                provider="paystack",
                provider_account_id=encrypt_payout_provider_account_id(
                    recipient.recipient_code
                ),
                provider_account_lookup_hash=lookup_hash,
                account_type="nuban",
                is_default=not await _has_active_payout_account(db, contributor_id),
                # Paystack resolved the account against the bank to create the
                # recipient, so there is nothing further to confirm.
                verified_at=datetime.now(UTC),
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
                    "provider": "paystack",
                    "account_type": "nuban",
                    "provider_account_ref": _masked_provider_ref(
                        recipient.recipient_code
                    ),
                    # Deliberately not the full account number: the masked
                    # recipient ref is enough to trace, and the audit log is
                    # read far more widely than the payout table.
                    "bank_code": payload.bank_code,
                },
            )
            if shared_with:
                await _audit_shared_payout_destination(
                    db,
                    actor_id=contributor_id,
                    payout_account=payout_account,
                    owner_count=shared_with + 1,
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
    ).info("payout_account_onboarded", provider="paystack")
    return PayoutAccountOnboardResponse(
        provider="paystack",
        onboarding_url=None,
        payout_account=_payout_account_response(payout_account),
        account_name=recipient.account_name,
    )


async def onboard_payout_account(
    db: AsyncSession,
    contributor: User,
    payload: PayoutAccountOnboardRequest,
) -> PayoutAccountOnboardResponse:
    """Create a provider-held payout destination for a KYC-verified Contributor.

    The rail is decided by the account's country, not by the caller. A Nigerian
    bank account registered against Stripe Connect could never be paid, so a
    provider that disagrees with the routing is refused rather than honoured.

    Args:
        db: Async SQLAlchemy session.
        contributor: The authenticated, KYC-verified Contributor.
        payload: Onboarding request naming the provider and account country.

    Returns:
        The stored payout account and, on the Stripe rail, a hosted onboarding
        URL to redirect the Contributor to.

    Raises:
        HTTPException(422): The requested provider does not settle that country.
        HTTPException(502): The payout provider rejected the request.
    """
    routed_provider = select_provider(
        user_country=payload.country,
        currency=platform_currency(),
    )
    if routed_provider != payload.provider:
        logger.bind(
            module="financials",
            action="onboard_payout_account",
            user_id=contributor.id,
        ).warning(
            "payout_provider_mismatch",
            requested=payload.provider,
            routed=routed_provider,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Payout accounts for {payload.country} settle on "
            f"{routed_provider}.",
        )
    if routed_provider == "paystack":
        return await _onboard_paystack_payout_account(db, contributor, payload)

    contributor_id = contributor.id

    # Narrowed by the request validator, which requires both URLs on this rail.
    assert payload.refresh_url is not None
    assert payload.return_url is not None

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
            ).error("payout_account_provider_failed: {error}", error=str(exc))
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
        ).error("payout_account_provider_failed: {error}", error=str(exc))
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


async def list_org_payout_accounts(
    db: AsyncSession,
    *,
    org_id: UUID,
) -> PayoutAccountsResponse:
    """List the organization's active payout destinations.

    Args:
        db: Async SQLAlchemy session.
        org_id: Organization whose destinations are read.

    Returns:
        The org's non-deleted payout accounts, newest first, with provider
        references masked.
    """
    payout_accounts = (
        (
            await db.execute(
                select(PayoutAccount)
                .where(
                    PayoutAccount.org_id == org_id,
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
    contributor: User,
    *,
    payout_account_id: UUID,
) -> PayoutAccountDeleteResponse:
    """Soft-delete an owned payout account.

    The route requires an open step-up window; no factor is checked here.
    """
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
