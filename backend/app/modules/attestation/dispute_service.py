"""Attestation dispute and admin intervention services.

Requestors use this module to dispute submitted reports before the dispute
window closes. Admins use the same boundary to resolve disputed reports or
manually handle `needs_admin` Attestations without drifting escrow state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.integrations import stripe
from app.integrations.stripe import StripeProviderError
from app.modules.attestation import notifications as attestation_notifications
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestorProfile,
)
from app.modules.attestation.schemas import AttestationDisputeCreateRequest
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.financials import escrow_service
from app.modules.financials.models import Escrow, PlatformConfig, Transaction

ACTIVE_DISPUTE_STATUSES = ("open", "under_review")
DEFAULT_COMPLETION_SLA_DAYS = 7


def _normalise_money(amount: Decimal) -> Decimal:
    """Return a two-decimal money value for dispute comparisons."""
    return amount.quantize(Decimal("0.01"))


async def create_dispute(
    *,
    db: AsyncSession,
    requestor: User,
    attestation_id: UUID,
    payload: AttestationDisputeCreateRequest,
) -> AttestationDispute:
    """Raise an active dispute against a report-submitted Attestation."""
    requestor_id = requestor.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        current_time = datetime.now(UTC)
        attestation = await _load_attestation_for_update(db, attestation_id)
        if attestation.requestor_id != requestor_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestation not found.",
            )
        if attestation.status != "report_submitted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only submitted Attestation reports can be disputed.",
            )
        if (
            attestation.dispute_window_ends_at is None
            or attestation.dispute_window_ends_at < current_time
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attestation dispute window has closed.",
            )
        await _reject_duplicate_active_dispute(db, attestation.id)
        dispute = AttestationDispute(
            attestation_id=attestation.id,
            raised_by=requestor_id,
            reason=payload.reason.strip(),
        )
        db.add(dispute)
        attestation.status = "disputed"
        await db.flush()
        await write_audit(
            db=db,
            actor_id=requestor_id,
            action="attestation_disputed",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"dispute_id": str(dispute.id)},
        )
        await db.refresh(dispute)
    attestation_notifications.notify_dispute_raised(attestation)
    return dispute


async def resolve_dispute(
    *,
    db: AsyncSession,
    redis: Redis,
    admin: User,
    dispute_id: UUID,
    resolution_type: str,
    release_amount: Decimal | None,
    refund_amount: Decimal | None,
    resolution_notes: str,
    totp_code: str,
) -> AttestationDispute:
    """Resolve an Attestation dispute and synchronize escrow state."""
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
        dispute = await db.scalar(
            select(AttestationDispute)
            .where(AttestationDispute.id == dispute_id)
            .with_for_update()
        )
        if dispute is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestation dispute not found.",
            )
        if dispute.status == "resolved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Resolved Attestation disputes cannot be resolved again.",
            )

        attestation = await _load_attestation_for_update(db, dispute.attestation_id)
        if attestation.status != "disputed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attestation is not in dispute.",
            )
        escrow = await _load_attestation_escrow(
            db=db,
            attestation=attestation,
        )
        transaction = await _load_escrow_transaction(db=db, escrow=escrow)
        normalized_release, normalized_refund = _validate_resolution_amounts(
            resolution_type=resolution_type,
            attestation_fee=attestation.fee_amount,
            release_amount=release_amount,
            refund_amount=refund_amount,
        )
        notes = resolution_notes.strip()
        now = datetime.now(UTC)
        if resolution_type == "release":
            await escrow_service.release(
                db,
                escrow_id=escrow.id,
                actor_id=admin_id,
                reason=notes,
                admin_override=True,
            )
            audit_action = "attestation_released"
        elif resolution_type == "refund":
            await _refund_escrow_to_stripe(
                escrow=escrow,
                transaction=transaction,
                reason=notes,
            )
            await escrow_service.refund(
                db,
                escrow_id=escrow.id,
                actor_id=admin_id,
                reason=notes,
                admin_override=True,
            )
            audit_action = "attestation_refunded"
        else:
            assert normalized_release is not None
            assert normalized_refund is not None
            await escrow_service.split(
                db,
                escrow_id=escrow.id,
                actor_id=admin_id,
                release_amount=normalized_release,
                refund_amount=normalized_refund,
                reason=notes,
                admin_override=True,
            )
            audit_action = "attestation_released"

        dispute.status = "resolved"
        dispute.resolution_type = resolution_type
        dispute.release_amount = normalized_release
        dispute.refund_amount = normalized_refund
        dispute.admin_id = admin_id
        dispute.resolution_notes = notes
        dispute.resolved_at = now
        attestation.status = "closed"
        attestation.closed_at = now
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="attestation_dispute_resolved",
            target_type="attestation_dispute",
            target_id=dispute.id,
            metadata={
                "attestation_id": str(attestation.id),
                "resolution_type": resolution_type,
                "escrow_id": str(escrow.id),
            },
        )
        await write_audit(
            db=db,
            actor_id=admin_id,
            action=audit_action,
            target_type="attestation",
            target_id=attestation.id,
            metadata={
                "reason": "dispute_resolution",
                "resolution_type": resolution_type,
                "dispute_id": str(dispute.id),
            },
        )
        await db.flush()
        await db.refresh(dispute)
    attestation_notifications.notify_dispute_resolved(
        attestation,
        resolution_type=resolution_type,
    )
    return dispute


async def assign_needs_admin_attestation(
    *,
    db: AsyncSession,
    redis: Redis,
    admin: User,
    attestation_id: UUID,
    attestor_id: UUID,
    reason: str,
    totp_code: str,
) -> Attestation:
    """Manually assign a needs-admin Attestation to an approved Attestor."""
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
        attestation = await _load_attestation_for_update(db, attestation_id)
        if attestation.status != "needs_admin":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only needs-admin Attestations can be manually assigned.",
            )
        profile = await db.scalar(
            select(AttestorProfile)
            .where(
                AttestorProfile.user_id == attestor_id,
                AttestorProfile.active.is_(True),
            )
            .with_for_update()
        )
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approved Attestor profile not found.",
            )
        if attestor_id in {attestation.requestor_id, attestation.target_id}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Attestor cannot attest their own target.",
            )
        transaction = await _load_completed_attestation_transaction(
            db=db,
            attestation_id=attestation.id,
        )
        current_time = datetime.now(UTC)
        completion_days = await _completion_sla_days(db, attestation.target_type)
        cohort_index = await _next_cohort_index(db, attestation.id)
        offer = AttestationOffer(
            attestation_id=attestation.id,
            attestor_id=attestor_id,
            cohort_index=cohort_index,
            status="accepted",
            offered_at=current_time,
            responded_at=current_time,
            expires_at=current_time,
        )
        db.add(offer)
        transaction.payee_id = attestor_id
        attestation.status = "accepted"
        attestation.attestor_id = attestor_id
        attestation.accepted_at = current_time
        attestation.completion_due_at = current_time + timedelta(days=completion_days)
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="attestation_accepted",
            target_type="attestation",
            target_id=attestation.id,
            metadata={
                "reason": reason.strip(),
                "admin_assigned": True,
                "attestor_id": str(attestor_id),
                "transaction_id": str(transaction.id),
            },
        )
        await db.flush()
    await db.refresh(attestation)
    attestation_notifications.notify_manual_assignment(attestation, attestor_id)
    return attestation


async def refund_needs_admin_attestation(
    *,
    db: AsyncSession,
    redis: Redis,
    admin: User,
    attestation_id: UUID,
    reason: str,
    totp_code: str,
) -> Attestation:
    """Refund and close a needs-admin Attestation when assignment cannot proceed."""
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
        attestation = await _load_attestation_for_update(db, attestation_id)
        if attestation.status != "needs_admin":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only needs-admin Attestations can be refunded here.",
            )
        escrow = await _load_attestation_escrow(db=db, attestation=attestation)
        transaction = await _load_escrow_transaction(db=db, escrow=escrow)
        await _refund_escrow_to_stripe(
            escrow=escrow,
            transaction=transaction,
            reason=reason,
            idempotency_prefix="attestation_needs_admin_refund",
        )
        await escrow_service.refund(
            db,
            escrow_id=escrow.id,
            actor_id=admin_id,
            reason=reason,
            admin_override=True,
        )
        attestation.status = "closed"
        attestation.closed_at = datetime.now(UTC)
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="attestation_refunded",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"reason": reason.strip(), "escrow_id": str(escrow.id)},
        )
        await db.flush()
    await db.refresh(attestation)
    attestation_notifications.notify_refunded(attestation, reason="needs_admin")
    return attestation


async def escalate_attestation_disputes(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Move stale open Attestation disputes into admin review."""
    current_time = now or datetime.now(UTC)
    cutoff = current_time - timedelta(days=7)
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        disputes = (
            (
                await db.execute(
                    select(AttestationDispute)
                    .where(
                        AttestationDispute.status == "open",
                        AttestationDispute.created_at < cutoff,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for dispute in disputes:
            dispute.status = "under_review"
            dispute.escalated_at = current_time
            await write_audit(
                db=db,
                actor_id=None,
                action="attestation_dispute_escalated",
                target_type="attestation_dispute",
                target_id=dispute.id,
                metadata={"attestation_id": str(dispute.attestation_id)},
            )
    return len(disputes)


async def _load_attestation_for_update(
    db: AsyncSession,
    attestation_id: UUID,
) -> Attestation:
    """Load and lock an Attestation or raise 404."""
    attestation = await db.scalar(
        select(Attestation).where(Attestation.id == attestation_id).with_for_update()
    )
    if attestation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    return attestation


async def _reject_duplicate_active_dispute(
    db: AsyncSession,
    attestation_id: UUID,
) -> None:
    """Reject a second active dispute for the same Attestation."""
    active_dispute_id = await db.scalar(
        select(AttestationDispute.id)
        .where(
            AttestationDispute.attestation_id == attestation_id,
            AttestationDispute.status.in_(ACTIVE_DISPUTE_STATUSES),
        )
        .limit(1)
    )
    if active_dispute_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation already has an active dispute.",
        )


async def _load_completed_attestation_transaction(
    *,
    db: AsyncSession,
    attestation_id: UUID,
) -> Transaction:
    """Load and lock a completed Attestation fee transaction."""
    transaction = await db.scalar(
        select(Transaction)
        .where(
            Transaction.ref_type == "attestation",
            Transaction.ref_id == attestation_id,
            Transaction.transaction_type == "attestation_fee",
            Transaction.status == "completed",
        )
        .with_for_update()
    )
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation fee is not funded.",
        )
    return transaction


async def _completion_sla_days(db: AsyncSession, target_type: str) -> int:
    """Return the configured completion SLA in days for an Attestation target."""
    return await _platform_int_config(
        db,
        key=f"attestation_completion_sla_days_{target_type}",
        default=DEFAULT_COMPLETION_SLA_DAYS,
        minimum=1,
    )


async def _next_cohort_index(db: AsyncSession, attestation_id: UUID) -> int:
    """Return the next zero-based cohort index for a manual admin assignment."""
    current_max = await db.scalar(
        select(AttestationOffer.cohort_index)
        .where(AttestationOffer.attestation_id == attestation_id)
        .order_by(AttestationOffer.cohort_index.desc())
        .limit(1)
    )
    if current_max is None:
        return 0
    return int(current_max) + 1


async def _platform_int_config(
    db: AsyncSession,
    *,
    key: str,
    default: int,
    minimum: int,
) -> int:
    """Read a positive integer platform configuration value."""
    configured = await db.scalar(
        select(PlatformConfig.value).where(PlatformConfig.key == key)
    )
    if configured is None:
        return default
    try:
        parsed = int(configured)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{key} configuration is invalid.",
        ) from exc
    if parsed < minimum:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{key} configuration is invalid.",
        )
    return parsed


async def _verify_admin_2fa(
    db: AsyncSession,
    redis: Redis,
    admin_id: UUID,
    totp_code: str,
) -> None:
    """Require a valid admin TOTP before sensitive Attestation admin writes."""
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


def _validate_resolution_amounts(
    *,
    resolution_type: str,
    attestation_fee: Decimal,
    release_amount: Decimal | None,
    refund_amount: Decimal | None,
) -> tuple[Decimal | None, Decimal | None]:
    """Validate resolution amounts against the Attestation fee amount."""
    fee = _normalise_money(attestation_fee)
    if resolution_type == "split":
        if release_amount is None or refund_amount is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Split resolution requires release and refund amounts.",
            )
        normalized_release = _normalise_money(release_amount)
        normalized_refund = _normalise_money(refund_amount)
        if normalized_release + normalized_refund != fee:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Split amounts must equal the Attestation fee.",
            )
        return normalized_release, normalized_refund
    if release_amount is not None or refund_amount is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Amounts are only accepted for split resolution.",
        )
    return None, None


async def _load_attestation_escrow(
    *,
    db: AsyncSession,
    attestation: Attestation,
) -> Escrow:
    """Load and lock escrow for an Attestation or raise typed errors."""
    if attestation.escrow_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation escrow is missing.",
        )
    escrow = await db.get(Escrow, attestation.escrow_id, with_for_update=True)
    if escrow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Escrow not found.",
        )
    if escrow.status != "held":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only held Attestation escrow can be resolved.",
        )
    return escrow


async def _load_escrow_transaction(
    *,
    db: AsyncSession,
    escrow: Escrow,
) -> Transaction:
    """Load and lock the escrow funding transaction."""
    transaction = await db.get(Transaction, escrow.transaction_id, with_for_update=True)
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Escrow funding transaction not found.",
        )
    return transaction


async def _refund_escrow_to_stripe(
    *,
    escrow: Escrow,
    transaction: Transaction,
    reason: str,
    idempotency_prefix: str = "attestation_dispute_refund",
) -> None:
    """Refund a full Attestation escrow through Stripe before local state changes."""
    if transaction.provider_ref is None:
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
            idempotency_key=f"{idempotency_prefix}:{escrow.id}",
        )
    except StripeProviderError as exc:
        logger.bind(
            module="attestation",
            action="resolve_dispute",
            escrow_id=escrow.id,
            transaction_id=transaction.id,
        ).error(
            "stripe_attestation_dispute_refund_failed",
            error=str(exc),
            reason=reason,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc
