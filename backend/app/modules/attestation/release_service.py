"""Attestation report acceptance and escrow release services."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.attestation import badge_service
from app.modules.attestation import notifications as attestation_notifications
from app.modules.attestation.models import Attestation, AttestationDispute
from app.modules.auth.models import User
from app.modules.financials import escrow_service
from app.modules.financials.models import Transaction


async def accept_report(
    *,
    db: AsyncSession,
    requestor: User,
    attestation_id: UUID,
) -> Attestation:
    """Release escrow early when the requestor accepts a submitted report."""
    requestor_id = requestor.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        attestation = await _load_releasable_attestation(
            db=db,
            attestation_id=attestation_id,
        )
        if attestation.requestor_id != requestor_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestation not found.",
            )
        await _release_and_close(
            db=db,
            attestation=attestation,
            actor_id=requestor_id,
            reason="requestor_accept_report",
        )
    await db.refresh(attestation)
    attestation_notifications.notify_released(
        attestation,
        reason="requestor_accept_report",
    )
    return attestation


async def auto_release_attestations(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Release undisputed report-submitted Attestations past dispute window."""
    current_time = now or datetime.now(UTC)
    attestation_ids = list(
        (
            await db.execute(
                select(Attestation.id).where(
                    Attestation.status == "report_submitted",
                    Attestation.dispute_window_ends_at.is_not(None),
                    Attestation.dispute_window_ends_at <= current_time,
                )
            )
        )
        .scalars()
        .all()
    )
    released_count = 0
    for attestation_id in attestation_ids:
        if db.in_transaction():
            await db.rollback()
        async with db.begin():
            attestation = await _load_releasable_attestation(
                db=db,
                attestation_id=attestation_id,
            )
            if await _has_open_dispute(db, attestation.id):
                continue
            await _release_and_close(
                db=db,
                attestation=attestation,
                actor_id=attestation.requestor_id,
                reason="auto_release_after_dispute_window",
            )
            released_count += 1
        attestation_notifications.notify_released(
            attestation,
            reason="auto_release_after_dispute_window",
        )
    return released_count


async def _release_and_close(
    *,
    db: AsyncSession,
    attestation: Attestation,
    actor_id: UUID,
    reason: str,
) -> None:
    """Release a report-submitted Attestation escrow and close the request."""
    if attestation.escrow_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation escrow is missing.",
        )
    if await _has_open_dispute(db, attestation.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Disputed Attestation reports cannot be released.",
        )

    now = datetime.now(UTC)
    await escrow_service.release(
        db=db,
        escrow_id=attestation.escrow_id,
        actor_id=actor_id,
        reason=reason,
    )
    await _credit_org_beneficiary(db=db, attestation=attestation)
    attestation.status = "closed"
    attestation.closed_at = now
    # A released report stood — stamp it publication-eligible for Module 6.
    attestation.report_published_eligible = True
    await write_audit(
        db=db,
        actor_id=actor_id,
        action="attestation_released",
        target_type="attestation",
        target_id=attestation.id,
        metadata={"reason": reason, "escrow_id": str(attestation.escrow_id)},
    )
    await badge_service.publish_badge(db=db, attestation=attestation)


async def _credit_org_beneficiary(
    *,
    db: AsyncSession,
    attestation: Attestation,
) -> None:
    """Credit the fee transaction to the attestor org at settlement.

    For org-staffed attestations the accept step never sets a transaction
    payee (individual attestations set ``payee_id`` at accept). Settlement is
    where the org earns: stamp ``payee_org_id`` on the completed fee
    transaction so it counts toward the org's payout balance. Split/commission
    math is untouched — only the beneficiary is set. Legacy individual
    attestations (``attestor_org_id is None``) already carry ``payee_id`` and
    are left unchanged.
    """
    if attestation.attestor_org_id is None:
        return
    transaction = await db.scalar(
        select(Transaction)
        .where(
            Transaction.ref_type == "attestation",
            Transaction.ref_id == attestation.id,
            Transaction.transaction_type == "attestation_fee",
        )
        .with_for_update()
    )
    if transaction is not None:
        transaction.payee_id = None
        transaction.payee_org_id = attestation.attestor_org_id


async def _load_releasable_attestation(
    *,
    db: AsyncSession,
    attestation_id: UUID,
) -> Attestation:
    """Load and lock a report-submitted Attestation or raise typed errors."""
    attestation = await db.scalar(
        select(Attestation).where(Attestation.id == attestation_id).with_for_update()
    )
    if attestation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    if attestation.status != "report_submitted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation report is not ready for release.",
        )
    return attestation


async def _has_open_dispute(db: AsyncSession, attestation_id: UUID) -> bool:
    """Return whether an Attestation has an unresolved dispute."""
    dispute_id = await db.scalar(
        select(AttestationDispute.id)
        .where(
            AttestationDispute.attestation_id == attestation_id,
            AttestationDispute.status.in_(("open", "under_review")),
        )
        .limit(1)
    )
    return dispute_id is not None
