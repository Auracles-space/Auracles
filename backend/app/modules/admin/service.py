"""Admin service logic."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.integrations import stripe
from app.integrations.stripe import StripeProviderError
from app.modules.auth import service as auth_service
from app.modules.auth.models import KycDocument, User, UserRole
from app.modules.financials import escrow_service
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.modules.frameworks.models import Framework, License
from app.modules.frameworks.models_artifact import Artifact, ArtifactRarityAudit
from app.modules.frameworks.pipeline_gate import (
    NEAR_DUPLICATE_JACCARD_THRESHOLD,
    evaluate_framework_pipeline,
)
from app.workers.tasks.processing.minhash_index import (
    remove_framework_artifacts_from_index,
)

EDITABLE_PLATFORM_CONFIG_KEYS = {
    "commission_rate",
    "min_payout_usd",
    "refund_window_hours",
    "attestation_fee_framework",
    "attestation_fee_contributor",
    "attestation_fee_operator",
    "attestation_fee_credential",
    "attestation_cohort_size",
    "attestation_completion_sla_days_framework",
    "attestation_completion_sla_days_contributor",
    "attestation_completion_sla_days_operator",
    "attestation_completion_sla_days_credential",
    "attestation_offer_accept_hours",
    "attestation_dispute_window_days",
    "saved_search_alert_cadence_hours",
}
COMMISSION_RATE_MAX = Decimal("0.50")
MIN_PAYOUT_USD_MIN = Decimal("1.00")
MIN_PAYOUT_USD_MAX = Decimal("100000.00")
REFUND_WINDOW_HOURS_MIN = 0
REFUND_WINDOW_HOURS_MAX = 720
SAVED_SEARCH_ALERT_CADENCE_HOURS_MIN = 1
SAVED_SEARCH_ALERT_CADENCE_HOURS_MAX = 168
ATTESTATION_FEE_RANGES = {
    "attestation_fee_framework": (Decimal("25.00"), Decimal("100000.00")),
    "attestation_fee_contributor": (Decimal("25.00"), Decimal("100000.00")),
    "attestation_fee_operator": (Decimal("25.00"), Decimal("100000.00")),
    "attestation_fee_credential": (Decimal("10.00"), Decimal("100000.00")),
}
ATTESTATION_INTEGER_RANGES = {
    "attestation_cohort_size": (1, 10),
    "attestation_completion_sla_days_framework": (1, 30),
    "attestation_completion_sla_days_contributor": (1, 30),
    "attestation_completion_sla_days_operator": (1, 30),
    "attestation_completion_sla_days_credential": (1, 30),
    "attestation_offer_accept_hours": (1, 168),
    "attestation_dispute_window_days": (1, 30),
}


async def assign_user_role(
    db: AsyncSession,
    admin: User,
    target_user_id: UUID,
    role: str,
) -> UserRole:
    """Assign a user role, approving Attestor when an admin performs it."""
    target = await db.scalar(select(User).where(User.id == target_user_id))
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    existing = await db.scalar(
        select(UserRole).where(
            UserRole.user_id == target_user_id,
            UserRole.role == role,
        )
    )
    if existing is None:
        existing = UserRole(user_id=target_user_id, role=role)
        db.add(existing)

    existing.approved_at = datetime.now(UTC)
    existing.approved_by = admin.id
    action = "attestor_approved" if role == "attestor" else "role_assigned"
    await write_audit(
        db=db,
        actor_id=admin.id,
        action=action,
        target_type="user",
        target_id=target_user_id,
        metadata={"role": role},
    )
    await db.commit()
    return existing


async def review_user_kyc(
    db: AsyncSession,
    admin: User,
    target_user_id: UUID,
    review_status: str,
    notes: str | None,
) -> KycDocument:
    """Review the latest KYC document and update the user's KYC status."""
    target = await db.scalar(select(User).where(User.id == target_user_id))
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    document = await db.scalar(
        select(KycDocument)
        .where(KycDocument.user_id == target_user_id)
        .order_by(desc(KycDocument.created_at))
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC document not found.",
        )

    document.status = review_status
    document.reviewed_by = admin.id
    document.reviewed_at = datetime.now(UTC)
    document.notes = notes
    target.kyc_status = review_status
    await write_audit(
        db=db,
        actor_id=admin.id,
        action="kyc_status_change",
        target_type="user",
        target_id=target_user_id,
        metadata={"status": review_status, "document_id": str(document.id)},
    )
    await db.commit()
    return document


async def suspend_framework(
    db: AsyncSession,
    admin: User,
    framework_id: UUID,
    reason: str,
) -> Framework:
    """Suspend a published Framework after admin moderation review."""
    framework = await db.scalar(select(Framework).where(Framework.id == framework_id))
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    if framework.status == "suspended":
        return framework
    if framework.status != "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only published Frameworks can be suspended.",
        )

    framework.status = "suspended"
    framework.rejection_reason = reason.strip()
    await write_audit(
        db=db,
        actor_id=admin.id,
        action="framework_suspended",
        target_type="framework",
        target_id=framework.id,
        metadata={"reason": framework.rejection_reason},
    )
    await db.commit()
    try:
        await remove_framework_artifacts_from_index(framework.id)
    except Exception as exc:
        logger.bind(
            module="admin",
            action="remove_framework_from_lsh",
            user_id=admin.id,
            framework_id=framework.id,
        ).error("artifact_lsh_remove_failed", error=str(exc))
    return framework


async def override_rarity_block(
    db: AsyncSession,
    admin: User,
    framework_id: UUID,
    reason: str,
) -> Framework:
    """Override near-duplicate rarity hard blocks for one Framework."""
    admin_id = admin.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        framework = await db.scalar(
            select(Framework).where(Framework.id == framework_id)
        )
        if framework is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )
        artifact_rows = (
            await db.execute(
                select(Artifact, ArtifactRarityAudit)
                .join(
                    ArtifactRarityAudit,
                    ArtifactRarityAudit.artifact_id == Artifact.id,
                )
                .where(
                    Artifact.framework_id == framework.id,
                    Artifact.current_for_framework.is_(True),
                    ArtifactRarityAudit.internal_jaccard
                    >= NEAR_DUPLICATE_JACCARD_THRESHOLD,
                    ArtifactRarityAudit.near_duplicate_overridden_at.is_(None),
                )
            )
        ).all()
        if not artifact_rows:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Framework has no active near-duplicate rarity block.",
            )
        now = datetime.now(UTC)
        normalized_reason = reason.strip()
        overridden_artifact_ids: list[str] = []
        for artifact, audit in artifact_rows:
            audit.near_duplicate_overridden_at = now
            audit.near_duplicate_overridden_by = admin_id
            audit.near_duplicate_override_reason = normalized_reason
            overridden_artifact_ids.append(str(artifact.id))
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="rarity_block_overridden",
            target_type="framework",
            target_id=framework.id,
            metadata={
                "artifact_ids": overridden_artifact_ids,
                "reason": normalized_reason,
            },
        )
        await evaluate_framework_pipeline(db, framework, force=True)
    await db.refresh(framework)
    logger.bind(
        module="admin",
        action="override_rarity_block",
        user_id=admin_id,
        framework_id=framework.id,
    ).info("rarity_block_overridden")
    return framework


async def grant_license(
    db: AsyncSession,
    admin: User,
    framework_id: UUID,
    operator_id: UUID,
    license_type: str,
    expires_at: datetime | None,
    seats_total: int | None,
) -> License:
    """Grant an Operator license to a Framework for Phase 2 admin flows."""
    admin_id = admin.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        framework = await db.scalar(
            select(Framework).where(Framework.id == framework_id)
        )
        if framework is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )
        operator = await db.scalar(select(User).where(User.id == operator_id))
        if operator is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Operator not found.",
            )
        existing = await db.scalar(
            select(License).where(
                License.framework_id == framework_id,
                License.operator_id == operator_id,
            )
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Operator already has a license for this Framework.",
            )

        resolved_seats_total = seats_total
        if license_type == "team" and resolved_seats_total is None:
            resolved_seats_total = 10
        license_row = License(
            framework_id=framework.id,
            operator_id=operator.id,
            license_type=license_type,
            status="active",
            version_at_grant=framework.version,
            expires_at=expires_at,
            seats_used=1,
            seats_total=resolved_seats_total,
        )
        db.add(license_row)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="license_granted",
            target_type="license",
            target_id=license_row.id,
            metadata={
                "framework_id": str(framework.id),
                "operator_id": str(operator.id),
                "version_at_grant": framework.version,
                "type": license_type,
            },
        )
    return license_row


async def list_platform_config(db: AsyncSession) -> list[PlatformConfig]:
    """Return platform financial configuration rows in stable key order."""
    result = await db.execute(select(PlatformConfig).order_by(PlatformConfig.key))
    return list(result.scalars().all())


def _format_decimal_config(value: Decimal) -> str:
    """Return a stable plain-string representation for decimal config values."""
    return format(value.normalize(), "f")


def _parse_decimal_config(key: str, raw_value: str) -> Decimal:
    """Parse a decimal admin config value or raise a 422 API error."""
    try:
        return Decimal(raw_value.strip())
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{key} must be a valid decimal number.",
        ) from exc


def _parse_integer_config(key: str, raw_value: str) -> int:
    """Parse a whole-number admin config value or raise a 422 API error."""
    try:
        return int(raw_value.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{key} must be a whole number.",
        ) from exc


def _normalise_platform_config_value(key: str, raw_value: str) -> str:
    """Validate and normalize an editable platform config value."""
    if key == "commission_rate":
        value = _parse_decimal_config(key, raw_value)
        if value < Decimal("0") or value > COMMISSION_RATE_MAX:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="commission_rate must be between 0 and 0.50.",
            )
        return _format_decimal_config(value.quantize(Decimal("0.0001")))

    if key == "min_payout_usd":
        value = _parse_decimal_config(key, raw_value)
        if value < MIN_PAYOUT_USD_MIN or value > MIN_PAYOUT_USD_MAX:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="min_payout_usd must be between 1.00 and 100000.00.",
            )
        return _format_decimal_config(value.quantize(Decimal("0.01")))

    if key == "refund_window_hours":
        try:
            hours = int(raw_value.strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="refund_window_hours must be a whole number.",
            ) from exc
        if hours < REFUND_WINDOW_HOURS_MIN or hours > REFUND_WINDOW_HOURS_MAX:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="refund_window_hours must be between 0 and 720.",
            )
        return str(hours)

    if key in ATTESTATION_FEE_RANGES:
        value = _parse_decimal_config(key, raw_value)
        minimum, maximum = ATTESTATION_FEE_RANGES[key]
        if value < minimum or value > maximum:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{key} must be between {minimum} and {maximum}.",
            )
        return _format_decimal_config(value.quantize(Decimal("0.01")))

    if key in ATTESTATION_INTEGER_RANGES:
        integer_value = _parse_integer_config(key, raw_value)
        integer_minimum, integer_maximum = ATTESTATION_INTEGER_RANGES[key]
        if integer_value < integer_minimum or integer_value > integer_maximum:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"{key} must be between "
                    f"{integer_minimum} and {integer_maximum}."
                ),
            )
        return str(integer_value)

    if key == "saved_search_alert_cadence_hours":
        hours = _parse_integer_config(key, raw_value)
        if (
            hours < SAVED_SEARCH_ALERT_CADENCE_HOURS_MIN
            or hours > SAVED_SEARCH_ALERT_CADENCE_HOURS_MAX
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="saved_search_alert_cadence_hours must be between 1 and 168.",
            )
        return str(hours)

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=f"{key} is not editable.",
    )


async def update_platform_config(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    updates: list[tuple[str, str]],
    reason: str,
    totp_code: str,
) -> list[PlatformConfig]:
    """Apply audited admin platform configuration changes."""
    admin_id = admin.id
    seen_keys: set[str] = set()
    normalised_updates: list[tuple[str, str]] = []
    for key, raw_value in updates:
        if key in seen_keys:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{key} can only be updated once per request.",
            )
        seen_keys.add(key)
        normalised_updates.append(
            (key, _normalise_platform_config_value(key, raw_value))
        )

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await _verify_admin_2fa(
            db=db,
            redis=redis,
            admin_id=admin_id,
            totp_code=totp_code,
        )
        for key, value in normalised_updates:
            config = await db.get(PlatformConfig, key)
            if config is None:
                config = PlatformConfig(key=key, value=value, updated_by=admin_id)
                db.add(config)
                old_value = None
            else:
                old_value = config.value
                config.value = value
                config.updated_by = admin_id
                config.updated_at = datetime.now(UTC)

            if old_value != value:
                await write_audit(
                    db=db,
                    actor_id=admin_id,
                    action="platform_config_updated",
                    target_type="platform_config",
                    metadata={
                        "key": key,
                        "old_value": old_value,
                        "new_value": value,
                        "reason": reason.strip(),
                    },
                )

    return await list_platform_config(db)


async def _verify_admin_2fa(
    db: AsyncSession,
    redis: Redis,
    admin_id: UUID,
    totp_code: str,
) -> None:
    """Require a valid admin TOTP or backup code before sensitive admin writes."""
    admin = await db.get(User, admin_id, with_for_update=True)
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        )
    await auth_service.verify_totp_for_sensitive_action(
        db=db,
        redis=redis,
        user=admin,
        code=totp_code,
    )


async def release_escrow_override(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    escrow_id: UUID,
    reason: str,
    totp_code: str,
) -> Escrow:
    """Release held escrow funds through an audited admin override."""
    admin_id = admin.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await _verify_admin_2fa(
            db=db,
            redis=redis,
            admin_id=admin_id,
            totp_code=totp_code,
        )
        escrow = await escrow_service.release(
            db,
            escrow_id=escrow_id,
            actor_id=admin_id,
            reason=reason,
            admin_override=True,
        )
    return escrow


async def refund_escrow_override(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    escrow_id: UUID,
    reason: str,
    totp_code: str,
) -> Escrow:
    """Refund held escrow funds through an audited admin override."""
    admin_id = admin.id

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await _verify_admin_2fa(
            db=db,
            redis=redis,
            admin_id=admin_id,
            totp_code=totp_code,
        )
        escrow = await db.get(Escrow, escrow_id, with_for_update=True)
        if escrow is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Escrow not found.",
            )
        if escrow.status == "refunded":
            return escrow
        if escrow.status == "released":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Released escrow cannot be refunded.",
            )
        transaction = await db.get(
            Transaction,
            escrow.transaction_id,
            with_for_update=True,
        )
        if transaction is None or transaction.provider_ref is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Escrow funding transaction is missing provider metadata.",
            )
        if transaction.provider != "stripe":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Unsupported escrow payment provider.",
            )
        try:
            await stripe.create_refund(
                payment_intent_id=transaction.provider_ref,
                amount=transaction.amount,
                currency=transaction.currency,
                idempotency_key=f"escrow_refund:{escrow_id}",
            )
        except StripeProviderError as exc:
            logger.bind(
                module="admin",
                action="refund_escrow_override",
                user_id=admin_id,
                escrow_id=escrow_id,
            ).error("stripe_escrow_refund_failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Payment provider is unavailable.",
            ) from exc
        escrow = await escrow_service.refund(
            db,
            escrow_id=escrow_id,
            actor_id=admin_id,
            reason=reason,
            admin_override=True,
        )
    return escrow
