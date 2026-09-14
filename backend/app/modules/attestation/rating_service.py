"""Attestation rating capture (Module 5 section 5.3).

Requestors rate a stood report 1-5 stars with an optional comment. The rating
is decoupled from escrow release (money never waits on a rating prompt), one
per attestation, immutable, and consumed later by Module 6 reputation scoring.

Maps to: Module 5 design spec section 4.3.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.attestation.models import Attestation, AttestationRating
from app.modules.auth.models import User


async def submit_rating(
    *,
    db: AsyncSession,
    requestor: User,
    attestation_id: UUID,
    stars: int,
    comment: str | None,
) -> AttestationRating:
    """Record the requestor's immutable 1-5 rating of a stood report.

    Validates that the rating user owns the attestation (404, existence-hiding),
    the report stood — ``closed`` via accept/auto-accept or dispute-``rejected``,
    excluding refund/CoI-upheld outcomes (409) — and no prior rating exists
    (409). The row is locked for update so concurrent submits resolve to a clean
    409 rather than a unique-constraint 500.

    Args:
        db: Async SQLAlchemy session.
        requestor: The authenticated requestor (must own the attestation).
        attestation_id: UUID of the attestation whose report is being rated.
        stars: Integer 1-5 (validated at the schema; re-checked defensively).
        comment: Optional free-text comment.

    Returns:
        The persisted rating row.

    Raises:
        HTTPException(404): Attestation missing or not owned by the requestor.
        HTTPException(409): Report did not stand, or already rated.
        HTTPException(422): Stars outside 1-5.
    """
    if stars < 1 or stars > 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Rating must be between 1 and 5 stars.",
        )
    requestor_id = requestor.id
    log = logger.bind(
        module="attestation",
        action="submit_rating",
        user_id=requestor_id,
        attestation_id=attestation_id,
    )
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        attestation = await db.scalar(
            select(Attestation)
            .where(Attestation.id == attestation_id)
            .with_for_update()
        )
        if attestation is None or attestation.requestor_id != requestor_id:
            log.warning("access_denied: not requestor or not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestation not found.",
            )
        if not _report_stood(attestation):
            log.warning("rating_denied: report did not stand")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only a stood attestation report can be rated.",
            )
        existing = await db.scalar(
            select(AttestationRating.id).where(
                AttestationRating.attestation_id == attestation.id
            )
        )
        if existing is not None:
            log.warning("rating_denied: duplicate rating")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attestation has already been rated.",
            )
        rating = AttestationRating(
            attestation_id=attestation.id,
            rated_by=requestor_id,
            stars=stars,
            comment=comment.strip() if comment else None,
        )
        db.add(rating)
        await write_audit(
            db=db,
            actor_id=requestor_id,
            action="attestation_rated",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"stars": stars},
        )
        await db.flush()
        await db.refresh(rating)
    log.info("attestation_rated")
    if attestation.attestor_org_id is not None:
        from app.workers.tasks.reputation import recompute_subject_task

        recompute_subject_task.delay("attestor_org", str(attestation.attestor_org_id))
    return rating


def _report_stood(attestation: Attestation) -> bool:
    """Return whether the attestation's report stood and is thus rateable.

    A report stands when it becomes publication-eligible: closed via accept /
    auto-accept, or a rejected dispute. Refund/CoI-upheld outcomes leave the
    flag false. Reads the single ``report_published_eligible`` stamp set on
    every release path (Module 5 spec section 4.9).
    """
    return bool(attestation.report_published_eligible)
