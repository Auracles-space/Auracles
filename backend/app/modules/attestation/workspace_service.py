"""Attestation review workspace service.

Assigned-Attestor operations for opening the review workspace and, in later
tasks, managing rubric scores and annotations. Workspace operations hide
attestation existence from non-assigned users by returning 404 on mismatch.

Maps to: design spec sections 4.1 to 4.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.attestation import rubrics
from app.modules.attestation.dependencies import resolve_attestor_actor
from app.modules.attestation.models import (
    Attestation,
    AttestationAnnotation,
    AttestationRubricDimension,
    AttestationRubricScore,
)
from app.modules.auth.models import User
from app.modules.organizations.models import OrgAttestorProfile

ANNOTATION_TYPES = {
    "endorsement",
    "concern",
    "jurisdictional_caveat",
    "revision_recommended",
}


async def load_workspace_attestation(
    db: AsyncSession,
    *,
    attestation_id: UUID,
    user_id: UUID,
    allowed_statuses: set[str],
    lock: bool = True,
    allow_managers: bool = False,
) -> Attestation:
    """Load one attestation for its attestor-side actor, hiding non-actors.

    Authorization is delegated to :func:`resolve_attestor_actor`: the reviewing
    member (or, during coexistence, the legacy assigned attestor) may act on
    write surfaces, and org owners/admins are admitted read-only when
    ``allow_managers`` is set. Unrelated callers receive 404.

    Args:
        db: Async database session.
        attestation_id: Attestation row to load.
        user_id: Authenticated caller's id (captured before any rollback).
        allowed_statuses: States in which the requested operation is permitted.
        lock: Whether to take a `FOR UPDATE` row lock.
        allow_managers: Whether org owners/admins are admitted (read surfaces).

    Returns:
        The matching attestation row.

    Raises:
        HTTPException: 404 when the attestation is missing or hidden from the
            caller, 403 when an attestor-org member is not authorized for the
            surface, or 409 when the status is not allowed.
    """
    statement = select(Attestation).where(Attestation.id == attestation_id)
    if lock:
        statement = statement.with_for_update()
    attestation = await db.scalar(statement)
    if attestation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    await resolve_attestor_actor(
        db, attestation=attestation, user_id=user_id, allow_managers=allow_managers
    )
    if attestation.status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation is not in a workspace-editable state.",
        )
    return attestation


async def _has_valid_coi(
    db: AsyncSession,
    *,
    attestation: Attestation,
    now: datetime,
) -> bool:
    """Return whether the staffed attestor org holds a current signed CoI.

    The CoI lives on the staffed org's :class:`OrgAttestorProfile`.
    """
    signed_at = await db.scalar(
        select(OrgAttestorProfile.coi_signed_at).where(
            OrgAttestorProfile.org_id == attestation.attestor_org_id,
            OrgAttestorProfile.active.is_(True),
        )
    )
    expires_at = await db.scalar(
        select(OrgAttestorProfile.coi_expires_at).where(
            OrgAttestorProfile.org_id == attestation.attestor_org_id,
            OrgAttestorProfile.active.is_(True),
        )
    )
    return signed_at is not None and expires_at is not None and expires_at > now


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
    attestor_id = attestor.id
    if db.in_transaction():
        await db.rollback()

    current_time = datetime.now(UTC)
    async with db.begin():
        attestation = await load_workspace_attestation(
            db,
            attestation_id=attestation_id,
            user_id=attestor_id,
            allowed_statuses={"accepted", "in_review"},
        )
        if attestation.status == "in_review":
            return attestation
        if attestation.content_ack_at is None or not attestation.content_ack_version:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Content acknowledgment is required before review starts.",
            )

        if not await _has_valid_coi(db, attestation=attestation, now=current_time):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A valid current CoI declaration is required.",
            )

        attestation.status = "in_review"
        attestation.review_started_at = current_time
        await write_audit(
            db=db,
            actor_id=attestor_id,
            action="attestation_review_started",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"review_type": attestation.review_type},
        )

    await db.refresh(attestation)
    return attestation


async def acknowledge_content(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
    content_ack: bool,
    ack_version: str,
) -> Attestation:
    """Record the staffed reviewing member's content-use acknowledgment.

    Org attestations are staffed through accept-and-staff, which assigns the
    reviewing member but does not acknowledge content use on their behalf. The
    reviewing member records that binding acknowledgment here, unlocking full
    framework-content access and, in turn, ``start_review``. Idempotent: once
    acknowledged, re-acknowledging returns the row unchanged.

    Args:
        db: Async database session.
        attestor: Authenticated caller (must be the reviewing member).
        attestation_id: Accepted attestation to acknowledge.
        content_ack: The caller's affirmative content-use acknowledgment.
        ack_version: Version string of the acknowledged content-use terms.

    Returns:
        The attestation row carrying the recorded acknowledgment.

    Raises:
        HTTPException: 404 when the attestation is hidden from the caller, 403
            when an org owner/admin (read-only) attempts the write, 409 outside
            the ``accepted`` state, or 422 when ``content_ack`` is not affirmed.
    """
    if not content_ack:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Content-use acknowledgment is required.",
        )
    attestor_id = attestor.id
    if db.in_transaction():
        await db.rollback()

    current_time = datetime.now(UTC)
    async with db.begin():
        attestation = await load_workspace_attestation(
            db,
            attestation_id=attestation_id,
            user_id=attestor_id,
            allowed_statuses={"accepted"},
        )
        if attestation.content_ack_at is not None:
            return attestation
        attestation.content_ack_at = current_time
        attestation.content_ack_version = ack_version
        await write_audit(
            db=db,
            actor_id=attestor_id,
            action="attestation_content_acknowledged",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"ack_version": ack_version},
        )

    await db.refresh(attestation)
    return attestation


@dataclass(frozen=True)
class RubricScoreView:
    """One saved rubric score resolved to its stable dimension key.

    Attributes:
        dimension_key: Stable rubric key within the attestation review type.
        score: Persisted draft score (1-5), or None if only a comment exists.
        comment: Persisted draft comment, or None.
    """

    dimension_key: str
    score: int | None
    comment: str | None


@dataclass(frozen=True)
class RubricDimensionView:
    """One rubric dimension the workspace must score, in display order.

    Attributes:
        key: Stable dimension key used by the score upsert route.
        label: Human label rendered beside the score control.
        weight: Dimension weight within the review type's rubric.
        display_order: Zero-based position within the rubric.
    """

    key: str
    label: str
    weight: float
    display_order: int


async def list_rubric_dimensions(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
) -> list[RubricDimensionView]:
    """List the rubric the workspace scores against, from the seeded table.

    The client used to carry its own copy of every rubric; serving the seeded
    rows keeps the panel, the quality gate, and the published report on one
    definition. The version is pinned to the attestation once a report has
    been submitted and otherwise follows the current rubric version.

    Args:
        db: Async database session.
        attestor: Authenticated caller, the reviewing member or an org manager.
        attestation_id: Attestation whose rubric is requested.

    Returns:
        Dimensions ordered by ``display_order``.

    Raises:
        HTTPException: 404 on assignee mismatch or 409 outside readable states.
    """
    attestation = await load_workspace_attestation(
        db,
        attestation_id=attestation_id,
        user_id=attestor.id,
        allowed_statuses={"in_review", "revision_requested", "report_submitted"},
        lock=False,
        allow_managers=True,
    )
    version = attestation.rubric_version or rubrics.RUBRIC_VERSION
    rows = await db.execute(
        select(AttestationRubricDimension)
        .where(
            AttestationRubricDimension.review_type == attestation.review_type,
            AttestationRubricDimension.version == version,
        )
        .order_by(AttestationRubricDimension.display_order)
    )
    return [
        RubricDimensionView(
            key=row.key,
            label=row.label,
            weight=float(row.weight),
            display_order=row.display_order,
        )
        for row in rows.scalars().all()
    ]


async def list_rubric_scores(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
) -> list[RubricScoreView]:
    """List the attestation's saved rubric scores keyed by dimension.

    Lets the review workspace rehydrate the rubric panel on reload. Reads are
    limited to the assigned reviewer and org managers; the score rows are joined
    to their dimension so the caller sees the stable dimension key rather than
    the internal dimension id.

    Args:
        db: Async database session.
        attestor: Authenticated caller, expected to be the reviewing member.
        attestation_id: Attestation whose saved rubric scores are requested.

    Returns:
        One :class:`RubricScoreView` per saved dimension score.

    Raises:
        HTTPException: 404 on assignee mismatch or 409 outside readable states.
    """
    await load_workspace_attestation(
        db,
        attestation_id=attestation_id,
        user_id=attestor.id,
        allowed_statuses={"in_review", "revision_requested", "report_submitted"},
        lock=False,
        allow_managers=True,
    )
    rows = await db.execute(
        select(
            AttestationRubricDimension.key,
            AttestationRubricScore.score,
            AttestationRubricScore.comment,
        )
        .join(
            AttestationRubricDimension,
            AttestationRubricDimension.id == AttestationRubricScore.dimension_id,
        )
        .where(AttestationRubricScore.attestation_id == attestation_id)
    )
    return [
        RubricScoreView(dimension_key=key, score=score, comment=comment)
        for key, score, comment in rows.all()
    ]


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
    attestor_id = attestor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        attestation = await load_workspace_attestation(
            db,
            attestation_id=attestation_id,
            user_id=attestor_id,
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


async def list_annotations(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
) -> list[AttestationAnnotation]:
    """List annotations for a visible attestation workspace.

    Args:
        db: Async database session.
        attestor: Authenticated assigned attestor.
        attestation_id: Attestation whose annotations should be listed.

    Returns:
        Ordered annotation rows for the attestation.

    Raises:
        HTTPException: 404 on assignee mismatch or 409 outside readable states.
    """
    await load_workspace_attestation(
        db,
        attestation_id=attestation_id,
        user_id=attestor.id,
        allowed_statuses={"in_review", "report_submitted"},
        lock=False,
        allow_managers=True,
    )
    rows = await db.scalars(
        select(AttestationAnnotation)
        .where(AttestationAnnotation.attestation_id == attestation_id)
        .order_by(AttestationAnnotation.created_at)
    )
    return list(rows)


async def create_annotation(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
    artifact_id: UUID | None,
    location_label: str,
    quoted_excerpt: str | None,
    annotation_type: str,
    comment: str,
) -> AttestationAnnotation:
    """Create one free-anchor annotation during in-review work.

    Args:
        db: Async database session.
        attestor: Authenticated assigned attestor.
        attestation_id: Workspace attestation receiving the annotation.
        artifact_id: Optional artifact reference tied to the note.
        location_label: Human-entered location marker.
        quoted_excerpt: Optional excerpt quoted from the artifact.
        annotation_type: Controlled annotation type enum value.
        comment: Required annotation body.

    Returns:
        The newly created annotation row.

    Raises:
        HTTPException: 404 on assignee mismatch, 409 outside `in_review`, or
            422 for an invalid annotation type.
    """
    if annotation_type not in ANNOTATION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unknown annotation type.",
        )
    attestor_id = attestor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        attestation = await load_workspace_attestation(
            db,
            attestation_id=attestation_id,
            user_id=attestor_id,
            allowed_statuses={"in_review"},
        )
        annotation = AttestationAnnotation(
            attestation_id=attestation.id,
            artifact_id=artifact_id,
            location_label=location_label,
            quoted_excerpt=quoted_excerpt,
            annotation_type=annotation_type,
            comment=comment,
        )
        db.add(annotation)
        await db.flush()

    await db.refresh(annotation)
    return annotation


async def _load_owned_annotation(
    db: AsyncSession,
    *,
    user_id: UUID,
    attestation_id: UUID,
    annotation_id: UUID,
) -> AttestationAnnotation:
    """Load one annotation from a workspace the caller may write.

    Args:
        db: Async database session.
        user_id: Authenticated reviewing member's id (rollback-safe).
        attestation_id: Parent workspace attestation.
        annotation_id: Annotation row to load.

    Returns:
        The matching annotation row.

    Raises:
        HTTPException: 404 when the workspace or annotation is hidden, or 409
            when the workspace is not editable.
    """
    await load_workspace_attestation(
        db,
        attestation_id=attestation_id,
        user_id=user_id,
        allowed_statuses={"in_review"},
    )
    annotation = await db.scalar(
        select(AttestationAnnotation).where(
            AttestationAnnotation.id == annotation_id,
            AttestationAnnotation.attestation_id == attestation_id,
        )
    )
    if annotation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation not found.",
        )
    return annotation


async def update_annotation(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
    annotation_id: UUID,
    location_label: str,
    quoted_excerpt: str | None,
    annotation_type: str,
    comment: str,
) -> AttestationAnnotation:
    """Replace the editable fields of one annotation.

    Args:
        db: Async database session.
        attestor: Authenticated assigned attestor.
        attestation_id: Parent workspace attestation.
        annotation_id: Annotation row being updated.
        location_label: New location label.
        quoted_excerpt: New optional excerpt.
        annotation_type: Replacement controlled enum value.
        comment: Replacement comment text.

    Returns:
        The updated annotation row.

    Raises:
        HTTPException: 404 on hidden resources, 409 outside `in_review`, or
            422 for an invalid annotation type.
    """
    if annotation_type not in ANNOTATION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unknown annotation type.",
        )
    attestor_id = attestor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        annotation = await _load_owned_annotation(
            db,
            user_id=attestor_id,
            attestation_id=attestation_id,
            annotation_id=annotation_id,
        )
        annotation.location_label = location_label
        annotation.quoted_excerpt = quoted_excerpt
        annotation.annotation_type = annotation_type
        annotation.comment = comment
        await db.flush()

    await db.refresh(annotation)
    return annotation


async def delete_annotation(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
    annotation_id: UUID,
) -> None:
    """Delete one annotation from an in-review workspace.

    Args:
        db: Async database session.
        attestor: Authenticated assigned attestor.
        attestation_id: Parent workspace attestation.
        annotation_id: Annotation row being removed.

    Raises:
        HTTPException: 404 on hidden resources or 409 outside `in_review`.
    """
    attestor_id = attestor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        annotation = await _load_owned_annotation(
            db,
            user_id=attestor_id,
            attestation_id=attestation_id,
            annotation_id=annotation_id,
        )
        await db.delete(annotation)
