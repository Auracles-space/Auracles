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
from app.modules.attestation import badge_service, matching_service
from app.modules.attestation import notifications as attestation_notifications
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestorWarning,
)
from app.modules.attestation.schemas import (
    AdminAttestationDisputeListItem,
    AttestationDisputeCreateRequest,
)
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.financials import escrow_service
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.modules.organizations.models import Organization, OrgMember
from app.shared.business_days import add_business_days


async def _reviewing_member_user_id(
    db: AsyncSession, attestation: Attestation
) -> UUID | None:
    """Resolve the user id of an attestation's reviewing member, if staffed."""
    if attestation.reviewing_member_id is None:
        return None
    member_user_id: UUID | None = await db.scalar(
        select(OrgMember.user_id).where(
            OrgMember.id == attestation.reviewing_member_id
        )
    )
    return member_user_id

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
        recipient_id = await _reviewing_member_user_id(db, attestation)
        await db.refresh(dispute)
    attestation_notifications.notify_dispute_raised(
        attestation, recipient_id=recipient_id
    )
    return dispute


async def list_admin_disputes(
    db: AsyncSession,
    *,
    status_value: str = "active",
) -> list[AdminAttestationDisputeListItem]:
    """Return Attestation disputes in one status for the admin triage queue.

    ``active`` covers both unresolved statuses (``open`` and ``under_review``),
    which is the queue that actually needs a verdict; the individual statuses
    and ``resolved`` are available for narrowing and for history.

    Ordered by resolution deadline, soonest first, so the dispute closest to
    breaching its SLA sits at the top. Creation order would not do it: a complex
    dispute carries a 15-business-day SLA against a standard one's 5, so an
    older dispute is often due later.

    Args:
        db: Async database session.
        status_value: ``active``, ``open``, ``under_review``, or ``resolved``.

    Returns:
        Queue rows joined to their attestation and attestor organization.

    Raises:
        HTTPException(422): If ``status_value`` is not a recognised filter. The
            router constrains this already; the check stays because returning an
            empty list for a typo would read as "nothing needs attention".
    """
    if status_value == "active":
        statuses = list(ACTIVE_DISPUTE_STATUSES)
    elif status_value in ("open", "under_review", "resolved"):
        statuses = [status_value]
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unknown dispute status filter.",
        )

    rows = (
        await db.execute(
            select(AttestationDispute, Attestation, Organization.name)
            .join(Attestation, Attestation.id == AttestationDispute.attestation_id)
            .outerjoin(
                Organization, Organization.id == Attestation.attestor_org_id
            )
            .where(AttestationDispute.status.in_(statuses))
            .order_by(
                AttestationDispute.resolution_due_at.asc().nulls_last(),
                AttestationDispute.created_at,
            )
        )
    ).all()

    return [
        AdminAttestationDisputeListItem(
            id=dispute.id,
            attestation_id=dispute.attestation_id,
            category=dispute.category,
            reason=dispute.reason,
            status=dispute.status,
            outcome=dispute.outcome,
            is_complex=dispute.is_complex,
            resolution_due_at=dispute.resolution_due_at,
            escalated_at=dispute.escalated_at,
            resolved_at=dispute.resolved_at,
            created_at=dispute.created_at,
            attestation_status=attestation.status,
            review_type=attestation.review_type,
            fee_amount=attestation.fee_amount,
            currency=attestation.currency,
            attestor_org_id=attestation.attestor_org_id,
            attestor_org_name=org_name,
        )
        for dispute, attestation, org_name in rows
    ]


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
            await _refund_escrow_at_provider(
                db=db,
                escrow=escrow,
                transaction=transaction,
                actor_id=admin_id,
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
        if outcome in _UPHELD_OUTCOMES and attestation.attestor_org_id is not None:
            warned_org_id = attestation.attestor_org_id
            warned_org_recipients = await _write_org_warning(
                db,
                org_id=attestation.attestor_org_id,
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
        reviewing_recipient_id = await _reviewing_member_user_id(db, attestation)
        await db.flush()
        await db.refresh(dispute)
    attestation_notifications.notify_dispute_resolved(
        attestation, outcome=outcome, recipient_id=reviewing_recipient_id
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
    attestor_org_id: UUID,
    reason: str,
    totp_code: str,
) -> Attestation:
    """Admin dispatches an offer to a chosen attestor org for a needs-admin request.

    The org-world admin fallback for a request that auto-matching could not
    staff. The admin picks the org only; the org then accepts the offer and
    staffs its own reviewing member through the normal offer flow. Bypasses the
    auto-match eligibility filter (sector/jurisdiction overlap) but keeps the
    integrity guards: the org's ``attestor`` capability must be active and the
    org must not conflict with the target (self-review guard).

    Args:
        db: Async database session.
        redis: Redis client for admin TOTP verification.
        admin: Authenticated admin performing the assignment.
        attestation_id: The needs-admin Attestation to dispatch.
        attestor_org_id: Attestor org to offer the request to.
        reason: Audit reason for the manual dispatch.
        totp_code: Admin TOTP code.

    Returns:
        The Attestation, now in ``offered`` status.

    Raises:
        HTTPException(409): The Attestation is not in ``needs_admin`` status.
        HTTPException(422): The org has a conflict of interest with the target.
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
        attestation = await _load_attestation_for_update(db, attestation_id)
        if attestation.status != "needs_admin":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only needs-admin Attestations can be manually assigned.",
            )
        await matching_service._require_active_attestor_capability(db, attestor_org_id)
        if attestor_org_id in await matching_service._excluded_org_ids(db, attestation):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Attestor org has a conflict of interest with this target.",
            )
        current_time = datetime.now(UTC)
        offer_hours = await matching_service._platform_int_config(
            db,
            key="attestation_offer_accept_hours",
            default=matching_service.DEFAULT_OFFER_ACCEPT_HOURS,
            minimum=1,
        )
        cohort_index = await _next_cohort_index(db, attestation.id)
        offer = AttestationOffer(
            attestation_id=attestation.id,
            org_id=attestor_org_id,
            cohort_index=cohort_index,
            status="offered",
            offered_at=current_time,
            expires_at=current_time + timedelta(hours=offer_hours),
        )
        db.add(offer)
        attestation.status = "offered"
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="attestation_offered",
            target_type="attestation",
            target_id=attestation.id,
            metadata={
                "reason": reason.strip(),
                "admin_assigned": True,
                "attestor_org_id": str(attestor_org_id),
            },
        )
        await db.flush()
        offer_id = offer.id
    await db.refresh(attestation)
    offers = list(
        (
            await db.execute(
                select(AttestationOffer).where(AttestationOffer.id == offer_id)
            )
        )
        .scalars()
        .all()
    )
    await matching_service.notify_new_offers(db, attestation, offers)
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
        await _refund_escrow_at_provider(
            db=db,
            escrow=escrow,
            transaction=transaction,
            actor_id=admin_id,
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


async def org_attestor_upheld_warning_count(
    db: AsyncSession,
    *,
    org_id: UUID,
    now: datetime | None = None,
) -> int:
    """Count an org's formal warnings in the trailing 12 months.

    Warnings keyed to ``attestor_org_id`` accrue on every upheld dispute
    (refund or revise) in the trailing 12 months. The rolling
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


async def refund_orphaned_fee_escrow(
    db: AsyncSession,
    *,
    attestation: Attestation,
    escrow: Escrow,
    transaction: Transaction,
) -> None:
    """Return a fee that settled against an Attestation already closed.

    The unpaid-fee sweep closes a checkout that went cold days ago, so a
    payment can still — rarely — settle afterwards. Raising in the webhook
    would retry forever and leave the money held against a dead request, so
    the escrow goes straight back to the payer on the rail it arrived on.

    Reuses the dispute refund leg rather than repeating it: two refund
    implementations are how Stripe and Paystack drift apart.

    Args:
        db: Session inside the caller's open transaction.
        attestation: The closed Attestation the payment arrived for.
        escrow: The freshly funded escrow to return.
        transaction: The funding transaction the refund is issued against.
    """
    await _refund_escrow_at_provider(
        db=db,
        escrow=escrow,
        transaction=transaction,
        actor_id=attestation.requestor_id,
        idempotency_prefix="attestation_orphaned_fee_refund",
    )


async def _refund_escrow_at_provider(
    *,
    db: AsyncSession,
    escrow: Escrow,
    transaction: Transaction,
    actor_id: UUID,
    idempotency_prefix: str = "attestation_dispute_refund",
) -> None:
    """Refund a full Attestation escrow on its funding rail before local state.

    Delegates to the shared escrow refund leg so Stripe and Paystack cannot
    drift apart; the caller-specific idempotency prefixes keep already-issued
    Stripe refunds stable.
    """
    await escrow_service.refund_at_provider(
        db,
        escrow=escrow,
        transaction=transaction,
        idempotency_prefix=idempotency_prefix,
        actor_id=actor_id,
    )
