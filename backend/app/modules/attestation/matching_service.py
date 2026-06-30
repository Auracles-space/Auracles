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
from app.modules.attestation.models import (
    Attestation,
    AttestationOffer,
    AttestorProfile,
    Credential,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import PlatformConfig, Transaction
from app.modules.frameworks.models import Framework

DEFAULT_COHORT_SIZE = 3
DEFAULT_OFFER_ACCEPT_HOURS = 48
DEFAULT_COMPLETION_SLA_DAYS = 7
TERMINAL_OFFER_STATUSES = {"accepted", "declined", "expired", "superseded"}
ACTIVE_ASSIGNMENT_STATUSES = {"accepted", "report_submitted", "disputed"}
DEFAULT_CONCURRENCY_CAP = 5
COI_REMINDER_LEAD_DAYS = 30


@dataclass(frozen=True)
class ScoredCandidate:
    """A scored, eligible Attestor candidate for one Attestation request."""

    user_id: UUID
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

    excluded_ids = await _excluded_attestor_ids(db, attestation)
    already_offered_ids = set(
        (
            await db.execute(
                select(AttestationOffer.attestor_id).where(
                    AttestationOffer.attestation_id == attestation.id
                )
            )
        )
        .scalars()
        .all()
    )
    excluded_ids.update(already_offered_ids)
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
            attestor_id=candidate.user_id,
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
            "attestor_ids": [str(candidate.user_id) for candidate in candidates],
            "scores": {
                str(candidate.user_id): candidate.score for candidate in candidates
            },
            "expires_at": expires_at.isoformat(),
        },
    )
    return offers


async def list_attestor_assignments(
    db: AsyncSession,
    *,
    attestor: User,
) -> list[tuple[AttestationOffer, Attestation]]:
    """Return active offered and accepted Attestations for one Attestor."""
    rows = await db.execute(
        select(AttestationOffer, Attestation)
        .join(Attestation, Attestation.id == AttestationOffer.attestation_id)
        .where(
            AttestationOffer.attestor_id == attestor.id,
            AttestationOffer.status.in_(("offered", "accepted")),
        )
        .order_by(AttestationOffer.offered_at.desc(), AttestationOffer.id)
    )
    return [(offer, attestation) for offer, attestation in rows.all()]


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


async def accept_attestation_offer(
    db: AsyncSession,
    *,
    attestation_id: UUID,
    attestor: User,
    content_ack: bool,
    ack_version: str,
) -> Attestation:
    """Accept a cohort offer and atomically assign the Attestation.

    Full framework-content access is gated on the content-use acknowledgment,
    so acceptance requires ``content_ack=True``.
    """
    if not content_ack:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Content-use acknowledgment is required to accept.",
        )
    attestor_id = attestor.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        current_time = datetime.now(UTC)
        attestation = await _load_locked_attestation(db, attestation_id)
        offer = await _load_locked_offer(
            db,
            attestation_id=attestation_id,
            attestor_id=attestor_id,
        )
        if offer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestation offer not found.",
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
        transaction = await _load_funded_fee_transaction(db, attestation.id)
        transaction.payee_id = attestor_id
        attestation.status = "accepted"
        attestation.attestor_id = attestor_id
        attestation.accepted_at = current_time
        attestation.content_ack_at = current_time
        attestation.content_ack_version = ack_version
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
        await write_audit(
            db=db,
            actor_id=attestor_id,
            action="attestation_accepted",
            target_type="attestation",
            target_id=attestation.id,
            metadata={
                "offer_id": str(offer.id),
                "transaction_id": str(transaction.id),
                "completion_due_at": attestation.completion_due_at.isoformat(),
            },
        )
    await db.refresh(attestation)
    attestation_notifications.notify_offer_accepted(attestation, attestor_id)
    return attestation


async def decline_attestation_offer(
    db: AsyncSession,
    *,
    attestation_id: UUID,
    attestor: User,
) -> Attestation:
    """Decline a cohort offer and advance matching when the cohort is exhausted."""
    attestor_id = attestor.id
    if db.in_transaction():
        await db.rollback()
    next_offers: list[AttestationOffer] = []
    async with db.begin():
        current_time = datetime.now(UTC)
        attestation = await _load_locked_attestation(db, attestation_id)
        offer = await _load_locked_offer(
            db,
            attestation_id=attestation_id,
            attestor_id=attestor_id,
        )
        if offer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestation offer not found.",
            )
        if offer.status != "offered":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attestation offer is no longer available.",
            )
        offer.status = "declined"
        offer.responded_at = current_time
        await write_audit(
            db=db,
            actor_id=attestor_id,
            action="attestation_declined",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"offer_id": str(offer.id)},
        )
        if await _current_cohort_is_exhausted(db, attestation.id, offer.cohort_index):
            attestation.status = "matching"
            next_offers = await offer_next_cohort(
                db,
                attestation_id=attestation.id,
                now=current_time,
            )
    await db.refresh(attestation)
    attestation_notifications.notify_offer_declined(attestation, attestor_id)
    attestation_notifications.notify_offers(attestation, next_offers)
    if attestation.status == "needs_admin":
        attestation_notifications.notify_needs_admin(attestation)
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
        expired_offers: list[AttestationOffer] = []
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
            if expired_ids:
                expired_offers = list(
                    (
                        await db.execute(
                            select(AttestationOffer).where(
                                AttestationOffer.id.in_(expired_ids)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            for offer_id in expired_ids:
                await write_audit(
                    db=db,
                    actor_id=None,
                    action="attestation_offer_expired",
                    target_type="attestation",
                    target_id=attestation_id,
                    metadata={"offer_id": str(offer_id)},
                )
            if (
                attestation.status == "offered"
                and await _current_cohort_is_exhausted(
                    db,
                    attestation_id,
                    cohort_index,
                )
            ):
                attestation.status = "matching"
                next_offers = await offer_next_cohort(
                    db,
                    attestation_id=attestation_id,
                    now=current_time,
                )
        for expired_offer in expired_offers:
            attestation_notifications.notify_offer_expired(attestation, expired_offer)
        attestation_notifications.notify_offers(attestation, next_offers)
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
    overdue_ids = list(
        (
            await db.execute(
                select(Attestation.id).where(
                    Attestation.status == "accepted",
                    Attestation.completion_due_at.is_not(None),
                    Attestation.completion_due_at <= current_time,
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
        old_attestor_id: UUID | None = None
        next_offers: list[AttestationOffer] = []
        async with db.begin():
            attestation = await _load_locked_attestation(db, attestation_id)
            if (
                attestation.status != "accepted"
                or attestation.completion_due_at is None
                or attestation.completion_due_at > current_time
                or attestation.attestor_id is None
            ):
                continue

            old_attestor_id = attestation.attestor_id
            transaction = await _load_completed_fee_transaction(db, attestation.id)
            old_offer = await _load_locked_offer(
                db,
                attestation_id=attestation.id,
                attestor_id=old_attestor_id,
            )
            if old_offer is not None and old_offer.status == "accepted":
                old_offer.status = "superseded"
                old_offer.responded_at = current_time

            transaction.payee_id = None
            attestation.status = "matching"
            attestation.attestor_id = None
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
                    "old_attestor_id": str(old_attestor_id),
                    "transaction_id": str(transaction.id),
                },
            )
            revoked_count += 1
            next_offers = await offer_next_cohort(
                db,
                attestation_id=attestation.id,
                now=current_time,
            )
        if old_attestor_id is not None:
            attestation_notifications.notify_reassigned(
                attestation,
                old_attestor_id=old_attestor_id,
            )
        attestation_notifications.notify_offers(attestation, next_offers)
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
                select(AttestorProfile).where(
                    AttestorProfile.active.is_(True),
                    AttestorProfile.coi_expires_at.is_not(None),
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
        if current_time >= expires_at:
            dispatched = attestation_notifications.notify_coi_lapsed(
                profile.user_id,
                expires_at=expires_at,
            )
        elif current_time >= reminder_window_start:
            dispatched = attestation_notifications.notify_coi_expiring(
                profile.user_id,
                expires_at=expires_at,
            )
        else:
            continue
        # Only mark reminded on a confirmed enqueue — a broker outage must not
        # silently skip this attestor until their next signing cycle.
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


async def _load_locked_offer(
    db: AsyncSession,
    *,
    attestation_id: UUID,
    attestor_id: UUID,
) -> AttestationOffer | None:
    """Load and row-lock one Attestor's offer for an Attestation."""
    return type_cast(
        AttestationOffer | None,
        await db.scalar(
            select(AttestationOffer)
            .where(
                AttestationOffer.attestation_id == attestation_id,
                AttestationOffer.attestor_id == attestor_id,
            )
            .with_for_update()
        )
    )


async def _load_funded_fee_transaction(
    db: AsyncSession,
    attestation_id: UUID,
) -> Transaction:
    """Load and lock the completed Attestation fee transaction."""
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
    if transaction.payee_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation fee payee is already assigned.",
        )
    return transaction


async def _load_completed_fee_transaction(
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


async def _excluded_attestor_ids(
    db: AsyncSession,
    attestation: Attestation,
) -> set[UUID]:
    """Return users who must never receive offers for this Attestation."""
    excluded_ids = {attestation.requestor_id}
    owner_id = await _target_owner_id(db, attestation)
    if owner_id is not None:
        excluded_ids.add(owner_id)
    return excluded_ids


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
        return type_cast(UUID | None, owner_id)
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


async def _active_assignment_count(db: AsyncSession, attestor_id: UUID) -> int:
    """Count one Attestor's active, content-holding assignments."""
    count = await db.scalar(
        select(func.count())
        .select_from(Attestation)
        .where(
            Attestation.attestor_id == attestor_id,
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
    """Score and rank eligible Attestors for one Attestation request.

    Args:
        db: Async database session.
        attestation: Request being matched.
        excluded_ids: Users already excluded from the candidate pool.
        limit: Maximum number of candidates to return.
        now: Reference timestamp for CoI-expiry checks.

    Returns:
        Ranked eligible candidates, best first, capped to ``limit``.
    """
    query = (
        select(AttestorProfile)
        .where(
            AttestorProfile.active.is_(True),
            AttestorProfile.specializations.op("&&")(
                sql_cast(attestation.requested_specializations, ARRAY(Text))
            ),
            AttestorProfile.jurisdictions.op("&&")(
                sql_cast(attestation.requested_jurisdictions, ARRAY(Text))
            ),
            AttestorProfile.coi_signed_at.is_not(None),
            AttestorProfile.coi_expires_at > now,
        )
    )
    if excluded_ids:
        query = query.where(AttestorProfile.user_id.not_in(excluded_ids))
    profiles = list((await db.execute(query)).scalars().all())
    if not profiles:
        return []

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
            attestor_id=profile.user_id,
        ):
            continue

        active_count = await _active_assignment_count(db, profile.user_id)
        if active_count >= concurrency_cap:
            continue

        factors = {
            "sector": scoring.sector_alignment(
                attestation.requested_specializations,
                profile.sectors,
                profile.specializations,
            ),
            "category": scoring.category_match(
                framework_category,
                profile.framework_categories,
            ),
            "credential": scoring.credential_relevance(),
            "availability": scoring.availability_score(active_count, concurrency_cap),
            "reputation": scoring.reputation_score(),
        }
        score, breakdown = scoring.compute_match_score(factors)
        scored_profiles.append(
            (
                score,
                profile.approved_at,
                profile.user_id,
                ScoredCandidate(
                    user_id=profile.user_id,
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
    if attestation.requestor_id == user.id or attestation.attestor_id == user.id:
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
    offer_id = await db.scalar(
        select(AttestationOffer.id)
        .where(
            AttestationOffer.attestation_id == attestation.id,
            AttestationOffer.attestor_id == user.id,
        )
        .limit(1)
    )
    return offer_id is not None
