"""Attestation matching, cohort offers, and Attestor response services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast as type_cast
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import cast as sql_cast
from sqlalchemy.types import Text

from app.core.audit import write_audit
from app.modules.attestation import notifications as attestation_notifications
from app.modules.attestation import scoring
from app.modules.attestation.dependencies import attestor_actor
from app.modules.attestation.models import (
    Attestation,
    AttestationOffer,
    Credential,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import PlatformConfig
from app.modules.frameworks.models import Framework
from app.modules.organizations.models import (
    Organization,
    OrgAttestorProfile,
    OrgCapability,
    OrgMember,
)

DEFAULT_COHORT_SIZE = 3
DEFAULT_OFFER_ACCEPT_HOURS = 48
DEFAULT_COMPLETION_SLA_DAYS = 7
TERMINAL_OFFER_STATUSES = {"accepted", "declined", "expired", "superseded"}
ACTIVE_ASSIGNMENT_STATUSES = {"accepted", "report_submitted", "disputed"}
DEFAULT_CONCURRENCY_CAP = 5
COI_REMINDER_LEAD_DAYS = 30
DEFAULT_COMPLETION_GRACE_HOURS = 24


@dataclass(frozen=True)
class ScoredCandidate:
    """A scored, eligible attestor-org candidate for one Attestation request."""

    org_id: UUID
    score: float
    breakdown: dict[str, float]


async def offer_next_cohort(
    db: AsyncSession,
    *,
    attestation_id: UUID,
    now: datetime | None = None,
) -> list[AttestationOffer]:
    """Offer the next eligible Attestor cohort for a matching Attestation."""
    current_time = now or datetime.now(UTC)
    attestation = await _load_locked_attestation(db, attestation_id)
    if attestation.status not in {"matching", "offered"}:
        return []
    if attestation.status == "offered":
        active_offer = await db.scalar(
            select(AttestationOffer.id)
            .where(
                AttestationOffer.attestation_id == attestation.id,
                AttestationOffer.status == "offered",
            )
            .limit(1)
        )
        if active_offer is not None:
            return []

    excluded_ids = await _excluded_org_ids(db, attestation)
    already_offered_ids = set(
        (
            await db.execute(
                select(AttestationOffer.org_id).where(
                    AttestationOffer.attestation_id == attestation.id
                )
            )
        )
        .scalars()
        .all()
    )
    excluded_ids.update(oid for oid in already_offered_ids if oid is not None)
    cohort_size = await _platform_int_config(
        db,
        key="attestation_cohort_size",
        default=DEFAULT_COHORT_SIZE,
        minimum=1,
    )
    candidates = await _rank_eligible_attestors(
        db,
        attestation=attestation,
        excluded_ids=excluded_ids,
        limit=cohort_size,
        now=current_time,
    )
    if not candidates:
        attestation.status = "needs_admin"
        await write_audit(
            db=db,
            actor_id=None,
            action="attestation_needs_admin",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"reason": "matching_cohorts_exhausted"},
        )
        logger.bind(
            module="attestation",
            action="offer_next_cohort",
            attestation_id=attestation.id,
        ).warning("attestation_needs_admin")
        return []

    offer_hours = await _platform_int_config(
        db,
        key="attestation_offer_accept_hours",
        default=DEFAULT_OFFER_ACCEPT_HOURS,
        minimum=1,
    )
    cohort_index = await _next_cohort_index(db, attestation.id)
    expires_at = current_time + timedelta(hours=offer_hours)
    offers = [
        AttestationOffer(
            attestation_id=attestation.id,
            org_id=candidate.org_id,
            cohort_index=cohort_index,
            status="offered",
            offered_at=current_time,
            expires_at=expires_at,
            match_score=candidate.score,
            score_breakdown=candidate.breakdown,
        )
        for candidate in candidates
    ]
    db.add_all(offers)
    attestation.status = "offered"
    await write_audit(
        db=db,
        actor_id=None,
        action="attestation_offered",
        target_type="attestation",
        target_id=attestation.id,
        metadata={
            "cohort_index": cohort_index,
            "org_ids": [str(candidate.org_id) for candidate in candidates],
            "scores": {
                str(candidate.org_id): candidate.score for candidate in candidates
            },
            "expires_at": expires_at.isoformat(),
        },
    )
    return offers


async def list_org_offers(
    db: AsyncSession,
    *,
    org_id: UUID,
) -> list[tuple[AttestationOffer, Attestation]]:
    """Return open and accepted cohort offers made to one attestor org."""
    rows = await db.execute(
        select(AttestationOffer, Attestation)
        .join(Attestation, Attestation.id == AttestationOffer.attestation_id)
        .where(
            AttestationOffer.org_id == org_id,
            AttestationOffer.status.in_(("offered", "accepted")),
        )
        .order_by(AttestationOffer.offered_at.desc(), AttestationOffer.id)
    )
    return [(offer, attestation) for offer, attestation in rows.all()]


async def list_org_attestations(
    db: AsyncSession,
    *,
    org_id: UUID,
    reviewing_member_id: UUID | None = None,
) -> list[Attestation]:
    """List an org's attestations; optionally scoped to one reviewing member.

    Owner/admin callers pass ``reviewing_member_id=None`` to see all org
    attestations; a plain member passes their own membership id to see only the
    rows they are staffed on.
    """
    query = select(Attestation).where(Attestation.attestor_org_id == org_id)
    if reviewing_member_id is not None:
        query = query.where(Attestation.reviewing_member_id == reviewing_member_id)
    query = query.order_by(Attestation.updated_at.desc(), Attestation.id)
    return list((await db.execute(query)).scalars().all())


async def get_attestation_for_user(
    db: AsyncSession,
    *,
    attestation_id: UUID,
    user: User,
) -> Attestation:
    """Load an Attestation visible to its requestor, Attestor, cohort, or admin."""
    attestation = await db.get(Attestation, attestation_id)
    if attestation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    if await _can_view_attestation(db, attestation=attestation, user=user):
        return attestation
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Attestation not found.",
    )


async def accept_org_offer(
    db: AsyncSession,
    *,
    offer_id: UUID,
    org_id: UUID,
    actor_id: UUID,
    reviewing_member_id: UUID,
) -> Attestation:
    """Accept an org cohort offer and staff it with a reviewing member.

    The org owner/admin (enforced by the router dependency) supplies the
    ``reviewing_member_id`` who will perform the review. Validates that the
    member belongs to the org, has signed the current NDA, and is under the
    per-member concurrency cap. Writes ``attestor_org_id`` +
    ``reviewing_member_id`` — never the legacy ``attestor_id``.

    Raises:
        HTTPException(403): Org attestor capability is not active.
        HTTPException(404): Offer or nominated member not found for this org.
        HTTPException(409): Offer is no longer available or has expired.
        HTTPException(422): Member is unsigned (``nda_required``) or at capacity
            (``member_at_capacity``).
    """

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        current_time = datetime.now(UTC)
        offer = await _load_locked_org_offer(db, offer_id=offer_id, org_id=org_id)
        attestation = await _load_locked_attestation(db, offer.attestation_id)
        await _require_active_attestor_capability(db, org_id)
        member = await _load_assignable_member(
            db,
            org_id=org_id,
            member_id=reviewing_member_id,
        )
        if attestation.status != "offered" or offer.status != "offered":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attestation offer is no longer available.",
            )
        if offer.expires_at <= current_time:
            offer.status = "expired"
            offer.responded_at = current_time
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attestation offer has expired.",
            )

        completion_days = await _completion_sla_days(db, attestation.target_type)
        attestation.status = "accepted"
        attestation.attestor_org_id = org_id
        attestation.reviewing_member_id = member.id
        attestation.accepted_at = current_time
        attestation.completion_due_at = current_time + timedelta(days=completion_days)
        offer.status = "accepted"
        offer.responded_at = current_time
        await db.execute(
            update(AttestationOffer)
            .where(
                AttestationOffer.attestation_id == attestation.id,
                AttestationOffer.id != offer.id,
                AttestationOffer.status == "offered",
            )
            .values(status="superseded", responded_at=current_time)
        )
        # reviewing_member_id is an internal assignment fact; kept out of any
        # public/requestor response schema, present only in the audit trail.
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="attestation_accepted",
            target_type="attestation",
            target_id=attestation.id,
            metadata={
                "offer_id": str(offer.id),
                "attestor_org_id": str(org_id),
                "reviewing_member_id": str(member.id),
                "completion_due_at": attestation.completion_due_at.isoformat(),
            },
        )
    await db.refresh(attestation)
    attestation_notifications.notify_org_offer_accepted(attestation, org_id=org_id)
    return attestation


async def decline_org_offer(
    db: AsyncSession,
    *,
    offer_id: UUID,
    org_id: UUID,
    actor_id: UUID,
) -> Attestation:
    """Decline an org cohort offer and advance matching when exhausted.

    Raises:
        HTTPException(403): Org attestor capability is not active.
        HTTPException(404): Offer not found for this org.
        HTTPException(409): Offer is no longer available.
    """
    if db.in_transaction():
        await db.rollback()
    next_offers: list[AttestationOffer] = []
    async with db.begin():
        current_time = datetime.now(UTC)
        offer = await _load_locked_org_offer(db, offer_id=offer_id, org_id=org_id)
        attestation = await _load_locked_attestation(db, offer.attestation_id)
        await _require_active_attestor_capability(db, org_id)
        if offer.status != "offered":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attestation offer is no longer available.",
            )
        offer.status = "declined"
        offer.responded_at = current_time
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="attestation_declined",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"offer_id": str(offer.id), "org_id": str(org_id)},
        )
        if await _current_cohort_is_exhausted(db, attestation.id, offer.cohort_index):
            attestation.status = "matching"
            next_offers = await offer_next_cohort(
                db,
                attestation_id=attestation.id,
                now=current_time,
            )
    await db.refresh(attestation)
    await notify_new_offers(db, attestation, next_offers)
    if attestation.status == "needs_admin":
        attestation_notifications.notify_needs_admin(attestation)
    return attestation


async def reassign_reviewing_member(
    db: AsyncSession,
    *,
    attestation_id: UUID,
    org_id: UUID,
    actor_id: UUID,
    reviewing_member_id: UUID,
) -> Attestation:
    """Restaff an accepted org attestation before its review starts.

    Allowed only while ``review_started_at`` is unset; after the reviewing
    member opens the workspace, only a platform admin may reassign
    (dispute/incident path).

    Raises:
        HTTPException(404): Attestation not assigned to this org, or member not
            found for this org.
        HTTPException(409): Review has already started.
        HTTPException(422): Member is unsigned (``nda_required``) or at capacity
            (``member_at_capacity``).
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        attestation = await _load_locked_attestation(db, attestation_id)
        if attestation.attestor_org_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestation not found.",
            )
        if attestation.review_started_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Review has started; reassignment requires an admin.",
            )
        member = await _load_assignable_member(
            db,
            org_id=org_id,
            member_id=reviewing_member_id,
        )
        previous_member_id = attestation.reviewing_member_id
        attestation.reviewing_member_id = member.id
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="attestation_reviewer_reassigned",
            target_type="attestation",
            target_id=attestation.id,
            metadata={
                "attestor_org_id": str(org_id),
                "previous_member_id": (
                    str(previous_member_id) if previous_member_id else None
                ),
                "reviewing_member_id": str(member.id),
            },
        )
    await db.refresh(attestation)
    return attestation


async def expire_stale_offers(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Expire stale Attestation offers and advance exhausted cohorts."""
    current_time = now or datetime.now(UTC)
    stale_rows = await db.execute(
        select(AttestationOffer.attestation_id, AttestationOffer.cohort_index)
        .where(
            AttestationOffer.status == "offered",
            AttestationOffer.expires_at <= current_time,
        )
        .distinct()
    )
    stale_cohorts = list(stale_rows.all())
    expired_count = 0
    for attestation_id, cohort_index in stale_cohorts:
        if db.in_transaction():
            await db.rollback()
        next_offers: list[AttestationOffer] = []
        async with db.begin():
            attestation = await _load_locked_attestation(db, attestation_id)
            result = await db.execute(
                update(AttestationOffer)
                .where(
                    AttestationOffer.attestation_id == attestation_id,
                    AttestationOffer.cohort_index == cohort_index,
                    AttestationOffer.status == "offered",
                    AttestationOffer.expires_at <= current_time,
                )
                .values(status="expired", responded_at=current_time)
                .returning(AttestationOffer.id)
            )
            expired_ids = [row[0] for row in result.all()]
            expired_count += len(expired_ids)
            for offer_id in expired_ids:
                await write_audit(
                    db=db,
                    actor_id=None,
                    action="attestation_offer_expired",
                    target_type="attestation",
                    target_id=attestation_id,
                    metadata={"offer_id": str(offer_id)},
                )
            if attestation.status == "offered" and await _current_cohort_is_exhausted(
                db,
                attestation_id,
                cohort_index,
            ):
                attestation.status = "matching"
                next_offers = await offer_next_cohort(
                    db,
                    attestation_id=attestation_id,
                    now=current_time,
                )
        await notify_new_offers(db, attestation, next_offers)
        if attestation.status == "needs_admin":
            attestation_notifications.notify_needs_admin(attestation)
    return expired_count


async def revoke_overdue_attestations(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Revoke accepted Attestations past SLA and advance them to matching."""
    current_time = now or datetime.now(UTC)
    grace_hours = await _platform_int_config(
        db,
        key="attestation_completion_grace_hours",
        default=DEFAULT_COMPLETION_GRACE_HOURS,
        minimum=0,
    )
    cutoff = current_time - timedelta(hours=grace_hours)
    overdue_ids = list(
        (
            await db.execute(
                select(Attestation.id).where(
                    Attestation.status.in_(("accepted", "in_review")),
                    Attestation.completion_due_at.is_not(None),
                    Attestation.completion_due_at <= cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    revoked_count = 0
    for attestation_id in overdue_ids:
        if db.in_transaction():
            await db.rollback()
        old_reviewer_user_id: UUID | None = None
        next_offers: list[AttestationOffer] = []
        async with db.begin():
            attestation = await _load_locked_attestation(db, attestation_id)
            if (
                attestation.status not in {"accepted", "in_review"}
                or attestation.completion_due_at is None
                or attestation.completion_due_at > cutoff
                or attestation.attestor_org_id is None
            ):
                continue

            old_org_id = attestation.attestor_org_id
            if attestation.reviewing_member_id is not None:
                old_reviewer_user_id = await db.scalar(
                    select(OrgMember.user_id).where(
                        OrgMember.id == attestation.reviewing_member_id
                    )
                )
            old_offer = await db.scalar(
                select(AttestationOffer)
                .where(
                    AttestationOffer.attestation_id == attestation.id,
                    AttestationOffer.org_id == old_org_id,
                    AttestationOffer.status == "accepted",
                )
                .with_for_update()
            )
            if old_offer is not None:
                old_offer.status = "superseded"
                old_offer.responded_at = current_time

            # The fee is credited to the org only at escrow release, so an
            # overdue revoke before release leaves the transaction untouched.
            attestation.status = "matching"
            attestation.attestor_org_id = None
            attestation.reviewing_member_id = None
            attestation.accepted_at = None
            attestation.completion_due_at = None
            await write_audit(
                db=db,
                actor_id=None,
                action="attestation_reassigned",
                target_type="attestation",
                target_id=attestation.id,
                metadata={
                    "reason": "completion_sla_missed",
                    "attestor_org_id": str(old_org_id),
                },
            )
            revoked_count += 1
            next_offers = await offer_next_cohort(
                db,
                attestation_id=attestation.id,
                now=current_time,
            )
        if old_reviewer_user_id is not None:
            attestation_notifications.notify_reassigned(
                attestation,
                old_attestor_id=old_reviewer_user_id,
            )
        await notify_new_offers(db, attestation, next_offers)
        if attestation.status == "needs_admin":
            attestation_notifications.notify_needs_admin(attestation)
    return revoked_count


async def expire_owner_consent(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Cancel operator-initiated requests whose owner-consent window elapsed.

    Args:
        db: Async database session.
        now: Optional current timestamp override for deterministic tests.

    Returns:
        The number of attestation requests cancelled.
    """
    current_time = now or datetime.now(UTC)
    consent_hours = await _platform_int_config(
        db,
        key="attestation_owner_consent_hours",
        default=72,
        minimum=1,
    )
    cutoff = current_time - timedelta(hours=consent_hours)
    cancelled: list[Attestation] = []
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        rows = await db.execute(
            select(Attestation)
            .where(
                Attestation.status == "pending_owner_consent",
                Attestation.created_at <= cutoff,
            )
            .with_for_update(skip_locked=True)
        )
        for attestation in rows.scalars().all():
            attestation.status = "cancelled"
            attestation.closed_at = current_time
            await write_audit(
                db=db,
                actor_id=None,
                action="attestation_consent_expired",
                target_type="attestation",
                target_id=attestation.id,
                metadata={"consent_hours": consent_hours},
            )
            cancelled.append(attestation)
    for attestation in cancelled:
        attestation_notifications.notify_consent_declined(attestation)
    return len(cancelled)


async def send_coi_resign_reminders(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Send one CoI reminder per active expiry cycle for eligible Attestors.

    Args:
        db: Async database session.
        now: Optional current timestamp override for deterministic tests.

    Returns:
        The number of reminders sent during this sweep.
    """
    current_time = now or datetime.now(UTC)
    lead_window = timedelta(days=COI_REMINDER_LEAD_DAYS)
    profiles = list(
        (
            await db.execute(
                select(OrgAttestorProfile).where(
                    OrgAttestorProfile.active.is_(True),
                    OrgAttestorProfile.coi_expires_at.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )

    sent = 0
    for profile in profiles:
        expires_at = profile.coi_expires_at
        if expires_at is None:
            continue
        reminder_window_start = expires_at - lead_window
        already_reminded = (
            profile.coi_reminder_sent_at is not None
            and profile.coi_reminder_sent_at >= reminder_window_start
        )
        if already_reminded:
            continue
        recipients = await _org_manager_ids(db, profile.org_id)
        if not recipients:
            continue
        if current_time >= expires_at:
            dispatched = all(
                attestation_notifications.notify_coi_lapsed(
                    recipient,
                    expires_at=expires_at,
                )
                for recipient in recipients
            )
        elif current_time >= reminder_window_start:
            dispatched = all(
                attestation_notifications.notify_coi_expiring(
                    recipient,
                    expires_at=expires_at,
                )
                for recipient in recipients
            )
        else:
            continue
        # Only mark reminded on a confirmed enqueue — a broker outage must not
        # silently skip this org until their next signing cycle.
        if not dispatched:
            continue
        profile.coi_reminder_sent_at = current_time
        sent += 1

    if sent:
        await db.commit()
    logger.bind(
        module="attestation",
        action="send_coi_resign_reminders",
    ).info("coi_reminders_sent", count=sent)
    return sent


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


async def _completion_sla_days(db: AsyncSession, target_type: str) -> int:
    """Return the configured completion SLA in days for an Attestation target."""
    return await _platform_int_config(
        db,
        key=f"attestation_completion_sla_days_{target_type}",
        default=DEFAULT_COMPLETION_SLA_DAYS,
        minimum=1,
    )


async def _load_locked_attestation(
    db: AsyncSession,
    attestation_id: UUID,
) -> Attestation:
    """Load and row-lock an Attestation or raise a typed 404."""
    attestation = await db.scalar(
        select(Attestation).where(Attestation.id == attestation_id).with_for_update()
    )
    if attestation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    return attestation


async def _load_locked_org_offer(
    db: AsyncSession,
    *,
    offer_id: UUID,
    org_id: UUID,
) -> AttestationOffer:
    """Load and row-lock one org's offer by id, or raise a typed 404."""
    offer = type_cast(
        AttestationOffer | None,
        await db.scalar(
            select(AttestationOffer)
            .where(
                AttestationOffer.id == offer_id,
                AttestationOffer.org_id == org_id,
            )
            .with_for_update()
        ),
    )
    if offer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation offer not found.",
        )
    return offer


async def _require_active_attestor_capability(db: AsyncSession, org_id: UUID) -> None:
    """Raise 403 ``capability_suspended`` unless the org attestor cap is active."""
    active = await db.scalar(
        select(OrgCapability.id).where(
            OrgCapability.org_id == org_id,
            OrgCapability.capability == "attestor",
            OrgCapability.status == "active",
        )
    )
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "capability_suspended"},
        )


async def _load_assignable_member(
    db: AsyncSession,
    *,
    org_id: UUID,
    member_id: UUID,
) -> OrgMember:
    """Load an org member and confirm they may be staffed on an attestation.

    Raises:
        HTTPException(404): Member does not belong to this org.
        HTTPException(422): Member has not signed the current NDA
            (``nda_required``) or is at the per-member concurrency cap
            (``member_at_capacity``).
    """
    from app.modules.organizations import nda_service

    member = await db.scalar(
        select(OrgMember).where(
            OrgMember.id == member_id,
            OrgMember.org_id == org_id,
        )
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this organization.",
        )
    if not await nda_service.member_is_assignable(db, member_id=member.id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error_code": "nda_required"},
        )
    concurrency_cap = await _platform_int_config(
        db,
        key="attestation_concurrency_cap",
        default=DEFAULT_CONCURRENCY_CAP,
        minimum=1,
    )
    if await _active_assignment_count(db, member.id) >= concurrency_cap:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error_code": "member_at_capacity"},
        )
    return member


async def _org_manager_ids(db: AsyncSession, org_id: UUID) -> list[UUID]:
    """Return user ids of the org's owner and admins (offer notification fanout)."""
    rows = await db.execute(
        select(OrgMember.user_id).where(
            OrgMember.org_id == org_id,
            OrgMember.role.in_(("owner", "admin")),
        )
    )
    return list(rows.scalars().all())


async def resolve_offer_recipients(
    db: AsyncSession,
    offers: list[AttestationOffer],
) -> dict[UUID, list[UUID]]:
    """Resolve owner/admin notification recipients per org offer while db is live."""
    recipients: dict[UUID, list[UUID]] = {}
    for offer in offers:
        if offer.org_id is not None:
            recipients[offer.id] = await _org_manager_ids(db, offer.org_id)
    return recipients


def dispatch_offer_notifications(
    attestation: Attestation,
    offers: list[AttestationOffer],
    recipients: dict[UUID, list[UUID]],
) -> None:
    """Dispatch offer-received notifications to org managers (post-commit)."""
    for offer in offers:
        if offer.org_id is not None:
            for recipient_id in recipients.get(offer.id, []):
                attestation_notifications.notify_org_offer_received(
                    attestation,
                    offer=offer,
                    recipient_id=recipient_id,
                )


async def notify_new_offers(
    db: AsyncSession,
    attestation: Attestation,
    offers: list[AttestationOffer],
) -> None:
    """Resolve org offer recipients and dispatch offer-received notifications."""
    recipients = await resolve_offer_recipients(db, offers)
    dispatch_offer_notifications(attestation, offers, recipients)


async def _excluded_org_ids(
    db: AsyncSession,
    attestation: Attestation,
) -> set[UUID]:
    """Return attestor orgs that must never receive offers for this Attestation.

    Self-review guard: exclude any org where the requestor is a member, and any
    org where the target framework's owner is a member. Per-declaration CoI
    screening against org ``coi_declarations`` happens later in ranking.
    """
    conflicted_user_ids = {attestation.requestor_id}
    owner_id = await _target_owner_id(db, attestation)
    if owner_id is not None:
        conflicted_user_ids.add(owner_id)
    org_ids = (
        (
            await db.execute(
                select(OrgMember.org_id).where(
                    OrgMember.user_id.in_(conflicted_user_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    return set(org_ids)


async def _target_owner_id(
    db: AsyncSession,
    attestation: Attestation,
) -> UUID | None:
    """Resolve the user owner for a target type when it is stored elsewhere."""
    if attestation.target_type in {"contributor", "operator"}:
        return attestation.target_id
    if attestation.target_type == "credential":
        owner_id = await db.scalar(
            select(Credential.user_id).where(Credential.id == attestation.target_id)
        )
        return owner_id
    if attestation.target_type == "framework":
        owner_id = await db.scalar(
            select(Framework.contributor_id).where(
                Framework.id == attestation.target_id
            )
        )
        return owner_id
    return None


def _coi_conflict_subjects(attestation: Attestation, owner_id: UUID | None) -> set[str]:
    """Return the linked platform ids that would conflict with this request."""
    subjects = {str(attestation.target_id), str(attestation.requestor_id)}
    if owner_id is not None:
        subjects.add(str(owner_id))
    return subjects


def _is_coi_conflicted(
    coi_declarations: list[dict[str, object]],
    conflict_subjects: set[str],
    *,
    attestor_id: UUID,
) -> bool:
    """Return True when any linked CoI declaration conflicts with the request."""
    for entry in coi_declarations:
        raw_subject_id = entry.get("subject_id")
        if raw_subject_id is None:
            continue
        try:
            subject_id = str(UUID(str(raw_subject_id)))
        except (TypeError, ValueError):
            logger.bind(
                module="attestation",
                action="coi_conflict_screen",
                attestor_id=attestor_id,
            ).warning("coi_declaration_malformed_subject_id")
            continue
        if subject_id in conflict_subjects:
            return True
    return False


async def _framework_category(db: AsyncSession, attestation: Attestation) -> str | None:
    """Return the target framework category, or None for non-framework targets."""
    if attestation.target_type != "framework":
        return None
    return type_cast(
        str | None,
        await db.scalar(
            select(Framework.category).where(Framework.id == attestation.target_id)
        ),
    )


async def _active_assignment_count(db: AsyncSession, member_id: UUID) -> int:
    """Count one reviewing member's active, content-holding assignments."""
    count = await db.scalar(
        select(func.count())
        .select_from(Attestation)
        .where(
            Attestation.reviewing_member_id == member_id,
            Attestation.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
        )
    )
    return int(count or 0)


async def _org_active_assignment_count(db: AsyncSession, org_id: UUID) -> int:
    """Count one attestor org's active, content-holding assignments."""
    count = await db.scalar(
        select(func.count())
        .select_from(Attestation)
        .where(
            Attestation.attestor_org_id == org_id,
            Attestation.status.in_(ACTIVE_ASSIGNMENT_STATUSES),
        )
    )
    return int(count or 0)


async def _rank_eligible_attestors(
    db: AsyncSession,
    *,
    attestation: Attestation,
    excluded_ids: set[UUID],
    limit: int,
    now: datetime,
) -> list[ScoredCandidate]:
    """Score and rank eligible attestor orgs for one Attestation request.

    Ranks ``OrgAttestorProfile`` rows whose org holds an active ``attestor``
    capability and whose organization is neither suspended nor deactivated.
    Orgs are not hard-excluded at the concurrency cap — the cap is enforced per
    reviewing member at accept time — but the org's active load still feeds the
    availability score factor.

    Args:
        db: Async database session.
        attestation: Request being matched.
        excluded_ids: Org ids already excluded from the candidate pool.
        limit: Maximum number of candidates to return.
        now: Reference timestamp for CoI-expiry checks.

    Returns:
        Ranked eligible org candidates, best first, capped to ``limit``.
    """
    query = (
        select(OrgAttestorProfile)
        .join(Organization, Organization.id == OrgAttestorProfile.org_id)
        .join(
            OrgCapability,
            (OrgCapability.org_id == OrgAttestorProfile.org_id)
            & (OrgCapability.capability == "attestor")
            & (OrgCapability.status == "active"),
        )
        .where(
            OrgAttestorProfile.active.is_(True),
            Organization.suspended_at.is_(None),
            Organization.deactivated_at.is_(None),
            OrgAttestorProfile.specializations.op("&&")(
                sql_cast(attestation.requested_specializations, ARRAY(Text))
            ),
            OrgAttestorProfile.jurisdictions.op("&&")(
                sql_cast(attestation.requested_jurisdictions, ARRAY(Text))
            ),
            OrgAttestorProfile.coi_signed_at.is_not(None),
            OrgAttestorProfile.coi_expires_at > now,
        )
    )
    if excluded_ids:
        query = query.where(OrgAttestorProfile.org_id.not_in(excluded_ids))
    profiles = list((await db.execute(query)).scalars().all())
    if not profiles:
        return []

    from app.modules.reputation.models import ReputationScore

    reputation_rows = await db.execute(
        select(
            ReputationScore.subject_id,
            ReputationScore.score,
            ReputationScore.is_provisional,
        ).where(
            ReputationScore.subject_type == "attestor",
            ReputationScore.subject_id.in_([profile.org_id for profile in profiles]),
        )
    )
    reputation_by_org = {
        subject_id: (score, is_provisional)
        for subject_id, score, is_provisional in reputation_rows.all()
    }

    owner_id = await _target_owner_id(db, attestation)
    conflict_subjects = _coi_conflict_subjects(attestation, owner_id)
    framework_category = await _framework_category(db, attestation)
    concurrency_cap = await _platform_int_config(
        db,
        key="attestation_concurrency_cap",
        default=DEFAULT_CONCURRENCY_CAP,
        minimum=1,
    )

    scored_profiles: list[tuple[float, datetime, UUID, ScoredCandidate]] = []
    for profile in profiles:
        if _is_coi_conflicted(
            profile.coi_declarations,
            conflict_subjects,
            attestor_id=profile.org_id,
        ):
            continue

        active_count = await _org_active_assignment_count(db, profile.org_id)

        rep = reputation_by_org.get(profile.org_id)
        if rep is not None and rep[1] is False and rep[0] is not None:
            rep_norm = float(rep[0]) / 100.0
        else:
            rep_norm = 0.5

        factors = {
            "sector": scoring.sector_alignment(
                attestation.requested_specializations,
                profile.sectors,
                profile.specializations,
            ),
            "category": scoring.category_match(
                framework_category,
                profile.functions,
            ),
            "credential": scoring.credential_relevance(),
            "availability": scoring.availability_score(
                min(active_count, concurrency_cap), concurrency_cap
            ),
            "reputation": scoring.reputation_score(rep_norm),
        }
        score, breakdown = scoring.compute_match_score(factors)
        scored_profiles.append(
            (
                score,
                profile.approved_at,
                profile.org_id,
                ScoredCandidate(
                    org_id=profile.org_id,
                    score=score,
                    breakdown=breakdown,
                ),
            )
        )

    scored_profiles.sort(key=lambda row: (-row[0], row[1], row[2]))
    return [row[3] for row in scored_profiles[:limit]]


async def _next_cohort_index(db: AsyncSession, attestation_id: UUID) -> int:
    """Return the next zero-based cohort index for an Attestation."""
    current_max = await db.scalar(
        select(func.max(AttestationOffer.cohort_index)).where(
            AttestationOffer.attestation_id == attestation_id
        )
    )
    if current_max is None:
        return 0
    return int(current_max) + 1


async def _current_cohort_is_exhausted(
    db: AsyncSession,
    attestation_id: UUID,
    cohort_index: int,
) -> bool:
    """Return True when no active offers remain in a cohort."""
    active_offer_id = await db.scalar(
        select(AttestationOffer.id)
        .where(
            AttestationOffer.attestation_id == attestation_id,
            AttestationOffer.cohort_index == cohort_index,
            AttestationOffer.status == "offered",
        )
        .limit(1)
    )
    return active_offer_id is None


async def _can_view_attestation(
    db: AsyncSession,
    *,
    attestation: Attestation,
    user: User,
) -> bool:
    """Check whether a user can see an Attestation detail response."""
    if attestation.requestor_id == user.id:
        return True
    role = await db.scalar(
        select(UserRole.role).where(
            UserRole.user_id == user.id,
            UserRole.role == "admin",
            UserRole.approved_at.is_not(None),
        )
    )
    if role == "admin":
        return True
    actor = await attestor_actor(db, attestation=attestation, user_id=user.id)
    if actor.is_reviewing_member or actor.is_org_manager:
        return True
    # Cohort org owner/admin holding an offer to their organization.
    offer_org_id = await db.scalar(
        select(AttestationOffer.org_id)
        .join(OrgMember, OrgMember.org_id == AttestationOffer.org_id)
        .where(
            AttestationOffer.attestation_id == attestation.id,
            OrgMember.user_id == user.id,
            OrgMember.role.in_(("owner", "admin")),
        )
        .limit(1)
    )
    return offer_org_id is not None
