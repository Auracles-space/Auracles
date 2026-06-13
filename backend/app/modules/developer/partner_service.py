"""Partner API marketplace read service.

Partner reads intentionally reuse public Explore visibility rules and response
mapping where possible. Partner endpoints may expose only public marketplace
metadata and explicitly gated preview/report metadata, never licensed artifacts
or private attestation evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from secrets import token_urlsafe
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.integrations import stripe
from app.integrations.stripe import StripeProviderError
from app.modules.attestation.models import Attestation
from app.modules.auth import service as auth_service
from app.modules.auth.models import User, UserRole
from app.modules.developer.auth import PartnerApiContext
from app.modules.developer.models import PartnerPurchaseAttribution
from app.modules.developer.schemas import (
    PartnerAttestationReportResponse,
    PartnerAttestationsResponse,
    PartnerFrameworkDetailResponse,
    PartnerPreviewArtifactResponse,
    PartnerPurchaseRequest,
    PartnerPurchaseResponse,
    PartnerPurchaseStatusResponse,
)
from app.modules.explore import service as explore_service
from app.modules.explore.schemas import (
    ExploreAttestationStatus,
    ExploreFrameworkListResponse,
    ExploreSort,
)
from app.modules.financials.models import PlatformConfig, Transaction
from app.modules.frameworks.models import Framework, License
from app.modules.frameworks.models_artifact import Artifact
from app.workers.tasks.notifications import send_verification_email

VERIFY_EMAIL_TTL_SECONDS = auth_service.VERIFY_EMAIL_TTL_SECONDS


def _normalise_money(amount: Decimal) -> Decimal:
    """Return a two-decimal money value for Partner purchase records."""
    return amount.quantize(Decimal("0.01"))


def _normalise_rate(rate: Decimal) -> Decimal:
    """Return a four-decimal commission rate for Stripe metadata snapshots."""
    return rate.quantize(Decimal("0.0001"))


def _invited_display_name(email: str) -> str:
    """Return a required display name for invited Operator accounts."""
    local_part = email.split("@", maxsplit=1)[0].replace(".", " ").replace("_", " ")
    display_name = local_part.strip().title() or "Invited Operator"
    return display_name[:100]


async def _platform_commission_rate(db: AsyncSession) -> Decimal:
    """Return the configured platform commission rate for margin validation."""
    configured = await db.scalar(
        select(PlatformConfig.value).where(PlatformConfig.key == "commission_rate")
    )
    if configured is None:
        return Decimal("0.15")
    try:
        return Decimal(configured)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commission_rate configuration is invalid.",
        ) from exc


async def _send_invited_operator_verification(
    redis: Redis,
    *,
    user_id: UUID,
    email: str,
) -> None:
    """Dispatch the existing email-verification flow for an invited buyer."""
    token = token_urlsafe(32)
    await redis.set(
        auth_service._verification_key(token),  # noqa: SLF001
        str(user_id),
        ex=VERIFY_EMAIL_TTL_SECONDS,
    )
    send_verification_email.delay(email, token)


async def _find_or_invite_operator(
    db: AsyncSession,
    redis: Redis,
    *,
    buyer_email: str,
) -> User:
    """Find an existing buyer or create an invited Operator account."""
    user = await db.scalar(select(User).where(User.email == buyer_email))
    if user is None:
        if db.in_transaction():
            await db.rollback()
        async with db.begin():
            user = User(
                email=buyer_email,
                password_hash=None,
                display_name=_invited_display_name(buyer_email),
                email_verified=False,
                kyc_status="unverified",
            )
            db.add(user)
            await db.flush()
            db.add(
                UserRole(
                    user_id=user.id,
                    role="operator",
                    approved_at=datetime.now(UTC),
                )
            )
            await write_audit(
                db=db,
                actor_id=None,
                action="partner_operator_invited",
                target_type="user",
                target_id=user.id,
                metadata={"email": buyer_email},
            )
        await _send_invited_operator_verification(
            redis,
            user_id=user.id,
            email=buyer_email,
        )
        return user

    user_id = user.id
    user_email_verified = user.email_verified
    operator_role_id = await db.scalar(
        select(UserRole.id).where(
            UserRole.user_id == user_id,
            UserRole.role == "operator",
        )
    )
    if operator_role_id is None:
        if db.in_transaction():
            await db.rollback()
        async with db.begin():
            db.add(
                UserRole(
                    user_id=user_id,
                    role="operator",
                    approved_at=datetime.now(UTC),
                )
            )
            await write_audit(
                db=db,
                actor_id=None,
                action="partner_operator_role_added",
                target_type="user",
                target_id=user_id,
                metadata={"email": buyer_email},
            )
        refreshed_user = await db.get(User, user_id)
        if refreshed_user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Buyer account not found.",
            )
        user = refreshed_user

    if not user_email_verified:
        await _send_invited_operator_verification(
            redis,
            user_id=user_id,
            email=buyer_email,
        )
    return user


async def _create_pending_partner_purchase(
    db: AsyncSession,
    *,
    api_key_id: UUID,
    developer_account_id: UUID,
    developer_user_id: UUID,
    buyer_id: UUID,
    customer_id: str,
    framework_id: UUID,
    contributor_id: UUID,
    amount: Decimal,
    currency: str,
    license_type: str,
    tier_at_sale: int,
    tier_rate: Decimal,
) -> UUID:
    """Persist pending transaction and Partner attribution atomically."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        buyer_row = await db.get(User, buyer_id)
        if buyer_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Buyer account not found.",
            )
        if buyer_row.stripe_customer_id is None:
            buyer_row.stripe_customer_id = customer_id
        transaction = Transaction(
            payer_id=buyer_id,
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
        db.add(
            PartnerPurchaseAttribution(
                api_key_id=api_key_id,
                developer_account_id=developer_account_id,
                transaction_id=transaction.id,
                framework_id=framework_id,
                buyer_user_id=buyer_id,
                license_type=license_type,
                tier_at_sale=tier_at_sale,
                tier_rate=tier_rate,
            )
        )
        await write_audit(
            db=db,
            actor_id=developer_user_id,
            action="partner_purchase_initiated",
            target_type="transaction",
            target_id=transaction.id,
            metadata={
                "api_key_id": str(api_key_id),
                "framework_id": str(framework_id),
                "buyer_user_id": str(buyer_id),
                "license_type": license_type,
                "tier_rate": str(tier_rate),
            },
        )
        return transaction.id


async def _mark_partner_purchase_failed(
    db: AsyncSession,
    *,
    actor_id: UUID,
    api_key_id: UUID,
    transaction_id: UUID,
    reason: str,
) -> None:
    """Mark a pending Partner purchase failed after provider setup failure."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        transaction = await db.get(Transaction, transaction_id)
        if transaction is not None:
            transaction.status = "failed"
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="partner_purchase_failed",
            target_type="transaction",
            target_id=transaction_id,
            metadata={"api_key_id": str(api_key_id), "reason": reason},
        )


async def _mark_partner_purchase_provider_ref(
    db: AsyncSession,
    *,
    actor_id: UUID,
    api_key_id: UUID,
    transaction_id: UUID,
    provider_ref: str,
) -> None:
    """Attach Stripe PaymentIntent id to a Partner purchase transaction."""
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
            actor_id=actor_id,
            action="partner_purchase_payment_intent_created",
            target_type="transaction",
            target_id=transaction.id,
            metadata={
                "api_key_id": str(api_key_id),
                "provider": "stripe",
            },
        )


async def list_catalog(
    db: AsyncSession,
    *,
    q: str | None,
    page: int,
    page_size: int,
    sort: ExploreSort,
    sector: str | None,
    industry: str | None,
    function: str | None,
    category: str | None,
    license_type: str | None,
    complexity: int | None,
    org_size: str | None,
    lifecycle_stage: str | None,
    jurisdiction: str | None,
    price_min: Decimal | None,
    price_max: Decimal | None,
    attestation_status: ExploreAttestationStatus | None,
) -> ExploreFrameworkListResponse:
    """Return published Framework catalog results for Partner API consumers."""
    return await explore_service.list_catalog(
        db,
        current_user_id=None,
        q=q,
        page=page,
        page_size=page_size,
        sort=sort,
        sector=sector,
        industry=industry,
        function=function,
        category=category,
        license_type=license_type,
        complexity=complexity,
        org_size=org_size,
        lifecycle_stage=lifecycle_stage,
        jurisdiction=jurisdiction,
        price_min=price_min,
        price_max=price_max,
        attestation_status=attestation_status,
    )


async def get_detail(
    db: AsyncSession,
    *,
    framework_id: UUID,
) -> PartnerFrameworkDetailResponse:
    """Return Partner-safe public detail for one published Framework."""
    framework = await db.scalar(
        select(Framework)
        .join(User, User.id == Framework.contributor_id)
        .where(
            Framework.id == framework_id,
            Framework.status == "published",
            User.suspended_at.is_(None),
        )
    )
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    rarity_scores = await explore_service._framework_rarity_scores(  # noqa: SLF001
        db,
        [framework.id],
    )
    attestation_badges = await explore_service._framework_attestation_badges(  # noqa: SLF001
        db,
        [framework.id],
    )
    review_aggregates = await explore_service._framework_review_aggregates(  # noqa: SLF001
        db,
        [framework.id],
    )
    contributor_names = await explore_service._user_display_names(  # noqa: SLF001
        db,
        [framework.contributor_id],
    )
    card = explore_service._card_from_framework(  # noqa: SLF001
        framework,
        rarity_scores.get(framework.id),
        attestation_badges.get(framework.id),
        review_aggregates.get(framework.id),
        contributor_names.get(framework.contributor_id, "Contributor"),
    )
    return PartnerFrameworkDetailResponse(
        **card.model_dump(),
        preview_artifact_id=framework.preview_artifact_id,
    )


async def get_preview(
    db: AsyncSession,
    redis: Redis,
    *,
    framework_id: UUID,
    client_ip: str,
) -> PartnerPreviewArtifactResponse:
    """Return the designated preview Artifact and URL for a published Framework."""
    framework = await db.scalar(
        select(Framework)
        .join(User, User.id == Framework.contributor_id)
        .where(
            Framework.id == framework_id,
            Framework.status == "published",
            User.suspended_at.is_(None),
        )
    )
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    if framework.preview_artifact_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preview artifact not found.",
        )
    preview_artifact = await db.scalar(
        select(Artifact).where(
            Artifact.id == framework.preview_artifact_id,
            Artifact.framework_id == framework.id,
            Artifact.current_for_framework.is_(True),
        )
    )
    if preview_artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preview artifact not found.",
        )
    preview_url = await explore_service._preview_url(  # noqa: SLF001
        redis,
        framework,
        preview_artifact,
        client_ip,
    )
    if preview_url is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preview artifact not found.",
        )
    return PartnerPreviewArtifactResponse(
        id=preview_artifact.id,
        name=preview_artifact.name,
        file_size=preview_artifact.file_size,
        mime_type=preview_artifact.mime_type,
        preview_url=preview_url,
        created_at=preview_artifact.created_at,
    )


async def list_attestations(
    db: AsyncSession,
    *,
    framework_id: UUID,
) -> PartnerAttestationsResponse:
    """Return public Attestation report metadata for one published Framework."""
    framework_exists = await db.scalar(
        select(Framework.id)
        .join(User, User.id == Framework.contributor_id)
        .where(
            Framework.id == framework_id,
            Framework.status == "published",
            User.suspended_at.is_(None),
        )
    )
    if framework_exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    rows = await db.execute(
        select(Attestation)
        .where(
            Attestation.target_type == "framework",
            Attestation.target_id == framework_id,
            Attestation.outcome.in_(
                explore_service.PUBLIC_POSITIVE_ATTESTATION_OUTCOMES
            ),
            Attestation.report_key.is_not(None),
            Attestation.status.in_(explore_service.PUBLIC_ATTESTATION_REPORT_STATUSES),
        )
        .order_by(
            Attestation.issued_at.desc().nullslast(),
            Attestation.created_at.desc(),
        )
    )
    return PartnerAttestationsResponse(
        attestations=[
            PartnerAttestationReportResponse(
                id=attestation.id,
                status=attestation.status,
                outcome=attestation.outcome,
                report_key=attestation.report_key,
                issued_at=attestation.issued_at,
            )
            for attestation in rows.scalars().all()
        ]
    )


async def initiate_purchase(
    db: AsyncSession,
    redis: Redis,
    *,
    context: PartnerApiContext,
    framework_id: UUID,
    payload: PartnerPurchaseRequest,
) -> PartnerPurchaseResponse:
    """Create a Partner-attributed pending purchase and Stripe PaymentIntent."""
    buyer_email = auth_service.normalize_email(str(payload.buyer_email))
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
    framework_uuid = framework.id
    contributor_id = framework.contributor_id
    framework_license_types = list(framework.license_types)
    framework_price = framework.price
    framework_currency = framework.currency.upper()
    if payload.license_type not in framework_license_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Selected license type is not available for this Framework.",
        )

    amount = _normalise_money(framework_price)
    currency = framework_currency
    if currency != "USD":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only USD purchases are supported.",
        )

    tier_rate = _normalise_rate(Decimal(context.developer_account.tier_rate))
    api_key_id = context.api_key.id
    developer_account_id = context.developer_account.id
    tier_at_sale = context.developer_account.commission_tier
    developer_user_id = context.developer_account.user_id
    platform_commission_rate = await _platform_commission_rate(db)
    if tier_rate > platform_commission_rate:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Partner tier rate cannot exceed platform commission rate.",
        )

    buyer = await _find_or_invite_operator(db, redis, buyer_email=buyer_email)
    buyer_id = buyer.id
    buyer_customer_id = buyer.stripe_customer_id
    buyer_display_name = buyer.display_name
    if buyer_id == contributor_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Buyer cannot purchase their own Framework.",
        )
    existing_license_id = await db.scalar(
        select(License.id)
        .where(
            License.framework_id == framework_uuid,
            License.operator_id == buyer_id,
            License.status == "active",
        )
        .limit(1)
    )
    if existing_license_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Framework is already licensed by this buyer.",
        )

    customer_id = buyer_customer_id
    try:
        if customer_id is None:
            customer = await stripe.create_customer(
                email=buyer_email,
                name=buyer_display_name,
                idempotency_key=f"partner_stripe_customer:{buyer_id}",
            )
            customer_id = customer.id
    except StripeProviderError as exc:
        logger.bind(
            module="developer",
            action="partner_purchase",
            framework_id=framework_uuid,
            user_id=developer_user_id,
        ).error("stripe_customer_create_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    transaction_id = await _create_pending_partner_purchase(
        db,
        api_key_id=api_key_id,
        developer_account_id=developer_account_id,
        developer_user_id=developer_user_id,
        buyer_id=buyer_id,
        customer_id=customer_id,
        framework_id=framework_uuid,
        contributor_id=contributor_id,
        amount=amount,
        currency=currency,
        license_type=payload.license_type,
        tier_at_sale=tier_at_sale,
        tier_rate=tier_rate,
    )
    try:
        payment_intent = await stripe.create_payment_intent(
            customer_id=customer_id,
            amount=amount,
            currency=currency,
            metadata={
                "transaction_id": str(transaction_id),
                "kind": "purchase",
                "framework_id": str(framework_uuid),
                "license_type": payload.license_type,
                "api_key_id": str(api_key_id),
                "tier_rate": str(tier_rate),
            },
            idempotency_key=f"partner_purchase:{transaction_id}",
        )
    except StripeProviderError as exc:
        await _mark_partner_purchase_failed(
            db,
            actor_id=developer_user_id,
            api_key_id=api_key_id,
            transaction_id=transaction_id,
            reason="payment_intent_create_failed",
        )
        logger.bind(
            module="developer",
            action="partner_purchase",
            framework_id=framework_uuid,
            transaction_id=transaction_id,
            user_id=developer_user_id,
        ).error("stripe_payment_intent_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    await _mark_partner_purchase_provider_ref(
        db,
        actor_id=developer_user_id,
        api_key_id=api_key_id,
        transaction_id=transaction_id,
        provider_ref=payment_intent.id,
    )
    logger.bind(
        module="developer",
        action="partner_purchase",
        framework_id=framework_uuid,
        transaction_id=transaction_id,
        user_id=developer_user_id,
    ).info("partner_purchase_initiated")
    return PartnerPurchaseResponse(
        transaction_id=transaction_id,
        provider="stripe",
        client_secret=payment_intent.client_secret,
    )


async def get_purchase_status(
    db: AsyncSession,
    *,
    context: PartnerApiContext,
    transaction_id: UUID,
) -> PartnerPurchaseStatusResponse:
    """Return status for a purchase initiated by the same Partner API key."""
    row = await db.execute(
        select(Transaction, PartnerPurchaseAttribution, User)
        .join(
            PartnerPurchaseAttribution,
            PartnerPurchaseAttribution.transaction_id == Transaction.id,
        )
        .join(User, User.id == PartnerPurchaseAttribution.buyer_user_id)
        .where(
            Transaction.id == transaction_id,
            PartnerPurchaseAttribution.api_key_id == context.api_key.id,
            PartnerPurchaseAttribution.developer_account_id
            == context.developer_account.id,
        )
    )
    result = row.one_or_none()
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purchase not found.",
        )
    transaction, attribution, buyer = result
    return PartnerPurchaseStatusResponse(
        transaction_id=transaction.id,
        status=transaction.status,
        provider="stripe",
        framework_id=attribution.framework_id,
        buyer_email=buyer.email,
        license_type=attribution.license_type,
        amount=transaction.amount,
        currency=transaction.currency,
    )
