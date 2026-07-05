"""Attestation dispute and admin intervention services.

Requestors use this module to dispute submitted reports before the dispute
window closes. Admins use the same boundary to resolve disputed reports or
manually handle `needs_admin` Attestations without drifting escrow state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.integrations import stripe
from app.integrations.stripe import StripeProviderError
from app.modules.attestation import badge_service
from app.modules.attestation import notifications as attestation_notifications
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestorProfile,
    AttestorWarning,
)
from app.modules.attestation.schemas import AttestationDisputeCreateRequest
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.financials import escrow_service
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.shared.business_days import add_business_days

ACTIVE_DISPUTE_STATUSES = ("open", "under_review")
DEFAULT_COMPLETION_SLA_DAYS = 7
DEFAULT_DISPUTE_EVIDENCE_MIN_LENGTH = 40
DEFAULT_REVISION_SLA_BUSINESS_DAYS = 5
RESOLUTION_SLA_STANDARD_BUSINESS_DAYS = 5
RESOLUTION_SLA_COMPLEX_BUSINESS_DAYS = 15
REQUESTOR_FLAG_THRESHOLD = 3
REQUESTOR_FLAG_WINDOW_DAYS = 365
SUSPENSION_REVIEW_THRESHOLD = 2
SUSPENSION_REVIEW_WINDOW_DAYS = 365
_UPHELD_OUTCOMES = ("upheld_refund", "upheld_revise")


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
        evidence = payload.reason.strip()
        min_length = await _evidence_min_length(db)
        if len(evidence) < min_length:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Dispute evidence is too short to substantiate the claim.",
            )
        dispute = AttestationDispute(
            attestation_id=attestation.id,
            raised_by=requestor_id,
            category=payload.category,
            reason=evidence,
            resolution_due_at=add_business_days(
                current_time, RESOLUTION_SLA_STANDARD_BUSINESS_DAYS
            ),
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
    outcome: str,
    resolution_notes: str,
    totp_code: str,
    is_complex: bool = False,
) -> AttestationDispute:
    """Resolve an Attestation dispute with a three-outcome verdict.

    Module 5 replaces the release/refund/split money-split model with a single
    ``outcome``:

    * ``rejected`` — the report stands. Escrow releases to the attestor, the
      attestation closes, and it becomes publication-eligible.
    * ``upheld_refund`` — the dispute is upheld with a refund. Escrow is refunded
      to the requestor, the attestation closes, and publication is suppressed.
    * ``upheld_revise`` — the dispute is upheld requiring a revision. Escrow stays
      held, the attestation reopens as ``revision_requested`` with a fresh
      revision SLA, and ``revision_count`` increments.

    Args:
        db: Async database session.
        redis: Redis client for admin TOTP verification.
        admin: Authenticated admin performing the resolution.
        dispute_id: Dispute being resolved.
        outcome: One of ``rejected``, ``upheld_refund``, ``upheld_revise``.
        resolution_notes: Admin's rationale (audited).
        totp_code: Admin TOTP for the sensitive action.

    Returns:
        The resolved dispute row.

    Raises:
        HTTPException(404): Dispute not found.
        HTTPException(409): Dispute already resolved, or attestation not disputed.
        HTTPException(502): Stripe refund failure on ``upheld_refund``.
    """
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
        if is_complex and not dispute.is_complex:
            # Complex disputes get the extended 15-business-day resolution SLA,
            # measured from when the dispute was raised.
            dispute.is_complex = True
            dispute.resolution_due_at = add_business_days(
                dispute.created_at, RESOLUTION_SLA_COMPLEX_BUSINESS_DAYS
            )
        notes = resolution_notes.strip()
        now = datetime.now(UTC)
        escrow_id_value: str | None = None
        warned_attestor_id: UUID | None = None
        warned_org_id: UUID | None = None
        warned_org_recipients: list[UUID] = []
        if outcome == "rejected":
            escrow = await _load_attestation_escrow(db=db, attestation=attestation)
            escrow_id_value = str(escrow.id)
            await escrow_service.release(
                db,
                escrow_id=escrow.id,
                actor_id=admin_id,
                reason=notes,
                admin_override=True,
            )
            attestation.status = "closed"
            attestation.closed_at = now
            attestation.report_published_eligible = True
            await badge_service.publish_badge(db=db, attestation=attestation)
            attestation_audit_action = "attestation_released"
        elif outcome == "upheld_refund":
            escrow = await _load_attestation_escrow(db=db, attestation=attestation)
            escrow_id_value = str(escrow.id)
            transaction = await _load_escrow_transaction(db=db, escrow=escrow)
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
            attestation.status = "closed"
            attestation.closed_at = now
            attestation.report_published_eligible = False
            attestation_audit_action = "attestation_refunded"
        else:  # upheld_revise — escrow stays held, report goes back for revision
            revision_sla = await _revision_sla_business_days(db)
            attestation.status = "revision_requested"
            attestation.revision_count += 1
            attestation.completion_due_at = add_business_days(now, revision_sla)
            attestation_audit_action = "attestation_revision_requested"

        dispute.status = "resolved"
        dispute.outcome = outcome
        dispute.admin_id = admin_id
        dispute.resolution_notes = notes
        dispute.resolved_at = now
        if outcome in _UPHELD_OUTCOMES:
            if attestation.attestor_org_id is not None:
                warned_org_id = attestation.attestor_org_id
                warned_org_recipients = await _write_org_warning(
                    db,
                    org_id=attestation.attestor_org_id,
                    dispute_id=dispute.id,
                    reason=f"Dispute upheld ({outcome}): {notes}",
                    now=now,
                )
            elif attestation.attestor_id is not None:
                warned_attestor_id = attestation.attestor_id
                await _write_warning(
                    db,
                    attestor_id=attestation.attestor_id,
                    dispute_id=dispute.id,
                    reason=f"Dispute upheld ({outcome}): {notes}",
                    now=now,
                )
        resolution_metadata: dict[str, str] = {
            "attestation_id": str(attestation.id),
            "outcome": outcome,
        }
        if escrow_id_value is not None:
            resolution_metadata["escrow_id"] = escrow_id_value
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="attestation_dispute_resolved",
            target_type="attestation_dispute",
            target_id=dispute.id,
            metadata=resolution_metadata,
        )
        await write_audit(
            db=db,
            actor_id=admin_id,
            action=attestation_audit_action,
            target_type="attestation",
            target_id=attestation.id,
            metadata={
                "reason": "dispute_resolution",
                "outcome": outcome,
                "dispute_id": str(dispute.id),
            },
        )
        await db.flush()
        await db.refresh(dispute)
    attestation_notifications.notify_dispute_resolved(attestation, outcome=outcome)
    if warned_attestor_id is not None:
        attestation_notifications.notify_attestor_warning(
            warned_attestor_id, reason=f"Dispute upheld ({outcome})."
        )
    if warned_org_id is not None:
        for recipient_id in warned_org_recipients:
            attestation_notifications.notify_org_attestor_warning(
                recipient_id,
                org_id=warned_org_id,
                reason=f"Dispute upheld ({outcome}).",
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
    """Flag Attestation disputes that missed their resolution SLA.

    Selects active disputes (``open`` or ``under_review``) whose
    ``resolution_due_at`` has passed and that are not already flagged, stamps
    ``resolution_overdue_at``, moves ``open`` disputes to ``under_review``, and
    audits the miss for admin attention. Money never moves here — there is no
    auto-resolve. Idempotent: a dispute already carrying
    ``resolution_overdue_at`` is skipped (spec section 4.8).

    Args:
        db: Async database session.
        now: Optional clock override for tests.

    Returns:
        The number of disputes newly flagged overdue.
    """
    current_time = now or datetime.now(UTC)
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        disputes = (
            (
                await db.execute(
                    select(AttestationDispute)
                    .where(
                        AttestationDispute.status.in_(ACTIVE_DISPUTE_STATUSES),
                        AttestationDispute.resolution_due_at.is_not(None),
                        AttestationDispute.resolution_due_at <= current_time,
                        AttestationDispute.resolution_overdue_at.is_(None),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for dispute in disputes:
            dispute.resolution_overdue_at = current_time
            if dispute.status == "open":
                dispute.status = "under_review"
                dispute.escalated_at = current_time
            await write_audit(
                db=db,
                actor_id=None,
                action="attestation_dispute_resolution_overdue",
                target_type="attestation_dispute",
                target_id=dispute.id,
                metadata={"attestation_id": str(dispute.attestation_id)},
            )
            logger.bind(
                module="attestation",
                action="attestation_dispute_resolution_overdue",
                dispute_id=dispute.id,
            ).warning("attestation_dispute_resolution_overdue")
    return len(disputes)


async def requestor_rejected_dispute_count(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    now: datetime | None = None,
) -> int:
    """Count a requestor's rejected disputes in the trailing 12 months.

    Rejected disputes (report stood against the requestor) are the abuse
    signal surfaced to attestors at match time. Derived, never stored.

    Maps to: Module 5 design spec section 4.5.
    """
    current_time = now or datetime.now(UTC)
    cutoff = current_time - timedelta(days=REQUESTOR_FLAG_WINDOW_DAYS)
    count = await db.scalar(
        select(func.count())
        .select_from(AttestationDispute)
        .where(
            AttestationDispute.raised_by == requestor_id,
            AttestationDispute.status == "resolved",
            AttestationDispute.outcome == "rejected",
            AttestationDispute.resolved_at.is_not(None),
            AttestationDispute.resolved_at >= cutoff,
        )
    )
    return int(count or 0)


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


async def _evidence_min_length(db: AsyncSession) -> int:
    """Return the configured minimum dispute-evidence character length."""
    return await _platform_int_config(
        db,
        key="attestation_dispute_evidence_min_length",
        default=DEFAULT_DISPUTE_EVIDENCE_MIN_LENGTH,
        minimum=1,
    )


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


async def _revision_sla_business_days(db: AsyncSession) -> int:
    """Return the configured revision-resubmission SLA in business days."""
    return await _platform_int_config(
        db,
        key="attestation_revision_sla_business_days",
        default=DEFAULT_REVISION_SLA_BUSINESS_DAYS,
        minimum=1,
    )


async def attestor_upheld_warning_count(
    db: AsyncSession,
    *,
    attestor_id: UUID,
    now: datetime | None = None,
) -> int:
    """Count an attestor's formal warnings in the trailing 12 months.

    Warnings accrue on every upheld dispute (refund or revise). The rolling
    count drives the suspension-review flag. Maps to spec section 4.7.
    """
    current_time = now or datetime.now(UTC)
    cutoff = current_time - timedelta(days=SUSPENSION_REVIEW_WINDOW_DAYS)
    count = await db.scalar(
        select(func.count())
        .select_from(AttestorWarning)
        .where(
            AttestorWarning.attestor_id == attestor_id,
            AttestorWarning.created_at >= cutoff,
        )
    )
    return int(count or 0)


async def org_attestor_upheld_warning_count(
    db: AsyncSession,
    *,
    org_id: UUID,
    now: datetime | None = None,
) -> int:
    """Count an org's formal warnings in the trailing 12 months.

    The org-level mirror of :func:`attestor_upheld_warning_count`: warnings
    keyed to ``attestor_org_id`` accrue on every upheld dispute. The rolling
    count drives the org's suspension-review flag (spec section 4.7).
    """
    current_time = now or datetime.now(UTC)
    cutoff = current_time - timedelta(days=SUSPENSION_REVIEW_WINDOW_DAYS)
    count = await db.scalar(
        select(func.count())
        .select_from(AttestorWarning)
        .where(
            AttestorWarning.attestor_org_id == org_id,
            AttestorWarning.created_at >= cutoff,
        )
    )
    return int(count or 0)


async def _write_org_warning(
    db: AsyncSession,
    *,
    org_id: UUID,
    dispute_id: UUID,
    reason: str,
    now: datetime,
) -> list[UUID]:
    """Record one org warning and flag suspension review if due.

    Writes the warning against the organization, and — when the rolling count
    reaches ``SUSPENSION_REVIEW_THRESHOLD`` — stamps the org attestor profile's
    ``suspension_review_at`` and audits it. Never deactivates an org; the flag
    is a human-review signal only. The reviewing member is never named.

    Returns:
        The owner/admin user ids to notify of the warning (resolved while the
        session is live, for post-commit dispatch).
    """
    from app.modules.attestation.matching_service import _org_manager_ids
    from app.modules.organizations.models import OrgAttestorProfile

    db.add(
        AttestorWarning(
            attestor_org_id=org_id,
            dispute_id=dispute_id,
            reason=reason,
        )
    )
    await db.flush()
    recipients = await _org_manager_ids(db, org_id)
    count = await org_attestor_upheld_warning_count(db, org_id=org_id, now=now)
    if count < SUSPENSION_REVIEW_THRESHOLD:
        return recipients
    profile = await db.scalar(
        select(OrgAttestorProfile)
        .where(OrgAttestorProfile.org_id == org_id)
        .with_for_update()
    )
    if profile is None or profile.suspension_review_at is not None:
        return recipients
    profile.suspension_review_at = now
    await write_audit(
        db=db,
        actor_id=None,
        action="org_attestor_suspension_review_flagged",
        target_type="attestor_org",
        target_id=org_id,
        metadata={"upheld_warnings": count},
    )
    logger.bind(
        module="attestation",
        action="org_attestor_suspension_review_flagged",
        org_id=org_id,
    ).warning("org_attestor_suspension_review_flagged")
    return recipients


async def _write_warning(
    db: AsyncSession,
    *,
    attestor_id: UUID,
    dispute_id: UUID,
    reason: str,
    now: datetime,
) -> None:
    """Record one attestor warning and flag suspension review if due.

    Writes the warning, notifies the attestor, and — when the rolling count
    reaches ``SUSPENSION_REVIEW_THRESHOLD`` — stamps the profile's
    ``suspension_review_at`` and audits it. Never deactivates an attestor; the
    flag is a human-review signal only (spec section 4.7).
    """
    db.add(
        AttestorWarning(
            attestor_id=attestor_id,
            dispute_id=dispute_id,
            reason=reason,
        )
    )
    await db.flush()
    count = await attestor_upheld_warning_count(db, attestor_id=attestor_id, now=now)
    if count < SUSPENSION_REVIEW_THRESHOLD:
        return
    profile = await db.scalar(
        select(AttestorProfile)
        .where(AttestorProfile.user_id == attestor_id)
        .with_for_update()
    )
    if profile is None or profile.suspension_review_at is not None:
        return
    profile.suspension_review_at = now
    await write_audit(
        db=db,
        actor_id=None,
        action="attestor_suspension_review_flagged",
        target_type="attestor_profile",
        target_id=profile.id,
        metadata={"upheld_warnings": count},
    )
    logger.bind(
        module="attestation",
        action="attestor_suspension_review_flagged",
        attestor_id=attestor_id,
    ).warning("attestor_suspension_review_flagged")


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
