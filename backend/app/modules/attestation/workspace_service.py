"""Attestation review workspace service.

Assigned-Attestor operations for opening the review workspace and, in later
tasks, managing rubric scores and annotations. Workspace operations hide
attestation existence from non-assigned users by returning 404 on mismatch.

Maps to: design spec sections 4.1 to 4.3.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.attestation import rubrics
from app.modules.attestation.models import (
    Attestation,
    AttestationRubricDimension,
    AttestationRubricScore,
    AttestorProfile,
)
from app.modules.auth.models import User


async def load_workspace_attestation(
    db: AsyncSession,
    *,
    attestation_id: UUID,
    attestor_id: UUID,
    allowed_statuses: set[str],
    lock: bool = True,
) -> Attestation:
    """Load one assigned attestation, hiding existence on assignee mismatch.

    Args:
        db: Async database session.
        attestation_id: Attestation row to load.
        attestor_id: Authenticated attestor expected to own the assignment.
        allowed_statuses: States in which the requested operation is permitted.
        lock: Whether to take a `FOR UPDATE` row lock.

    Returns:
        The matching attestation row.

    Raises:
        HTTPException: 404 when the attestation is missing or assigned to a
            different attestor, or 409 when the status is not allowed.
    """
    statement = select(Attestation).where(Attestation.id == attestation_id)
    if lock:
        statement = statement.with_for_update()
    attestation = await db.scalar(statement)
    if attestation is None or attestation.attestor_id != attestor_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    if attestation.status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation is not in a workspace-editable state.",
        )
    return attestation


async def start_review(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
) -> Attestation:
    """Open the review workspace, moving an accepted assignment into review.

    Args:
        db: Async database session.
        attestor: Authenticated assigned attestor opening the workspace.
        attestation_id: Attestation to transition.

    Returns:
        The attestation in `in_review` state.

    Raises:
        HTTPException: 404 when the attestation is hidden from the caller, 409
            for invalid states, or 422 when prerequisites are not satisfied.
    """
    if db.in_transaction():
        await db.rollback()

    current_time = datetime.now(UTC)
    async with db.begin():
        attestation = await load_workspace_attestation(
            db,
            attestation_id=attestation_id,
            attestor_id=attestor.id,
            allowed_statuses={"accepted", "in_review"},
        )
        if attestation.status == "in_review":
            return attestation
        if attestation.content_ack_at is None or not attestation.content_ack_version:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Content acknowledgment is required before review starts.",
            )

        profile = await db.scalar(
            select(AttestorProfile).where(
                AttestorProfile.user_id == attestor.id,
                AttestorProfile.active.is_(True),
            )
        )
        if (
            profile is None
            or profile.coi_signed_at is None
            or profile.coi_expires_at is None
            or profile.coi_expires_at <= current_time
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A valid current CoI declaration is required.",
            )

        attestation.status = "in_review"
        attestation.review_started_at = current_time
        await write_audit(
            db=db,
            actor_id=attestor.id,
            action="attestation_review_started",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"review_type": attestation.review_type},
        )

    await db.refresh(attestation)
    return attestation


async def upsert_rubric_score(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
    dimension_key: str,
    score: int | None,
    comment: str | None,
) -> AttestationRubricScore:
    """Create or update the attestor's draft score for one rubric dimension.

    Args:
        db: Async database session.
        attestor: Authenticated assigned attestor.
        attestation_id: Workspace attestation receiving the score.
        dimension_key: Stable rubric key within the attestation review type.
        score: Optional draft score in the 1-5 range.
        comment: Optional draft comment.

    Returns:
        The created or updated rubric-score row.

    Raises:
        HTTPException: 404 on assignee mismatch, 409 outside `in_review`, or
            422 for an invalid score or dimension key.
    """
    if score is not None and not 1 <= score <= 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Score must be between 1 and 5.",
        )
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        attestation = await load_workspace_attestation(
            db,
            attestation_id=attestation_id,
            attestor_id=attestor.id,
            allowed_statuses={"in_review"},
        )
        dimension = await db.scalar(
            select(AttestationRubricDimension).where(
                AttestationRubricDimension.review_type == attestation.review_type,
                AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
                AttestationRubricDimension.key == dimension_key,
            )
        )
        if dimension is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Unknown rubric dimension for this review type.",
            )

        row = await db.scalar(
            select(AttestationRubricScore).where(
                AttestationRubricScore.attestation_id == attestation.id,
                AttestationRubricScore.dimension_id == dimension.id,
            )
        )
        if row is None:
            row = AttestationRubricScore(
                attestation_id=attestation.id,
                dimension_id=dimension.id,
                score=score,
                comment=comment,
            )
            db.add(row)
        else:
            row.score = score
            row.comment = comment
        await db.flush()

    await db.refresh(row)
    return row
