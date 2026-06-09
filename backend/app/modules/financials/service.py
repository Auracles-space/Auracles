"""Business services for financial transactions and payouts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.integrations import stripe
from app.integrations.stripe import StripeProviderError
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.financials.models import PayoutAccount, PlatformConfig, Transaction
from app.modules.financials.schemas import (
    PaymentMethodDeleteResponse,
    PaymentMethodResponse,
    PaymentMethodSetupResponse,
    PaymentMethodsResponse,
    PayoutAccountDeleteResponse,
    PayoutAccountOnboardRequest,
    PayoutAccountOnboardResponse,
    PayoutAccountResponse,
    PayoutAccountsResponse,
    PurchaseRequest,
    PurchaseResponse,
    RefundResponse,
)
from app.modules.frameworks.models import Framework, License
from app.modules.frameworks.models_artifact import ArtifactDownload


def _masked_provider_ref(provider_ref: str) -> str:
    """Return a log-safe provider reference that preserves only the last chars."""
    return f"****{provider_ref[-4:]}" if len(provider_ref) > 4 else "****"


def _payout_account_response(payout_account: PayoutAccount) -> PayoutAccountResponse:
    """Map a payout account row to safe Contributor-facing metadata."""
    return PayoutAccountResponse(
        id=payout_account.id,
        provider="stripe",
        account_type=payout_account.account_type,
        provider_account_ref=_masked_provider_ref(payout_account.provider_account_id),
        is_default=payout_account.is_default,
        verified_at=payout_account.verified_at,
        created_at=payout_account.created_at,
    )


def _normalise_money(amount: Decimal) -> Decimal:
    """Return a two-decimal money value for persisted payment records."""
    return amount.quantize(Decimal("0.01"))


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
        select(License).where(
            License.transaction_id == transaction.id,
            License.operator_id == operator_id,
            License.status == "active",
        )
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


async def refund_framework_purchase(
    db: AsyncSession,
    operator: User,
    *,
    transaction_id: UUID,
) -> RefundResponse:
    """Refund an eligible Framework purchase and revoke its License."""
    operator_id = operator.id
    transaction, license_row = await _load_refundable_purchase(
        db=db,
        operator_id=operator_id,
        transaction_id=transaction_id,
    )
    payment_intent_id = transaction.provider_ref
    if payment_intent_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Purchase is missing refundable provider metadata.",
        )
    amount = _normalise_money(transaction.amount)
    currency = transaction.currency.upper()
    license_id = license_row.id

    try:
        refund = await stripe.create_refund(
            payment_intent_id=payment_intent_id,
            amount=amount,
            currency=currency,
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

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        transaction_row = await db.get(Transaction, transaction_id)
        license_to_revoke = await db.get(License, license_id)
        if transaction_row is None or license_to_revoke is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase not found.",
            )
        transaction_row.status = "refunded"
        license_to_revoke.status = "revoked"
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="purchase_refunded",
            target_type="transaction",
            target_id=transaction_row.id,
            metadata={
                "provider": "stripe",
                "refund_ref": _masked_provider_ref(refund.id),
                "license_id": str(license_to_revoke.id),
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


async def onboard_payout_account(
    db: AsyncSession,
    contributor: User,
    payload: PayoutAccountOnboardRequest,
) -> PayoutAccountOnboardResponse:
    """Create a provider-held payout destination for a KYC-verified Contributor."""
    contributor_id = contributor.id

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
                provider_account_id=provider_account_id,
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
        await db.execute(
            select(PayoutAccount)
            .where(
                PayoutAccount.user_id == contributor.id,
                PayoutAccount.deleted_at.is_(None),
            )
            .order_by(PayoutAccount.created_at.desc())
        )
    ).scalars().all()
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
    payout_account = await db.scalar(
        select(PayoutAccount).where(
            PayoutAccount.id == payout_account_id,
            PayoutAccount.user_id == contributor.id,
            PayoutAccount.deleted_at.is_(None),
        )
    )
    if payout_account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payout account not found.",
        )

    await auth_service.verify_totp_for_sensitive_action(
        db=db,
        redis=redis,
        user=contributor,
        code=totp_code,
    )
    await db.commit()

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        payout_account = await db.scalar(
            select(PayoutAccount).where(
                PayoutAccount.id == payout_account_id,
                PayoutAccount.user_id == contributor.id,
                PayoutAccount.deleted_at.is_(None),
            )
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
            actor_id=contributor.id,
            action="payout_account_deleted",
            target_type="payout_account",
            target_id=payout_account.id,
            metadata={
                "provider": payout_account.provider,
                "account_type": payout_account.account_type,
                "provider_account_ref": _masked_provider_ref(
                    payout_account.provider_account_id
                ),
            },
        )

    logger.bind(
        module="financials",
        action="delete_payout_account",
        user_id=contributor.id,
    ).info("payout_account_deleted")
    return PayoutAccountDeleteResponse(
        payout_account_id=payout_account_id,
        deleted=True,
    )
