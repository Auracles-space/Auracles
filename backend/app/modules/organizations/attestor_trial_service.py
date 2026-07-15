"""Org Attestor calibration-trial service.

Provides the nominee-facing trial workspace loader used by the member-scoped
trial page. Trial grading and admin decisioning are layered in later slices.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations import s3
from app.modules.attestation import rubrics, trial_scoring
from app.modules.attestation.models import (
    AttestationRubricDimension,
    AttestorTrial,
    AttestorTrialAnswerKey,
    AttestorTrialRubricScore,
)
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.modules.organizations.models import OrgAttestorApplication, OrgMember
from app.modules.organizations.schemas import (
    NomineeTrialResponse,
    TrialArtifactSchema,
    TrialRubricDimensionSchema,
    TrialScoreInput,
    TrialSubmitRequest,
)

_OPEN_TRIAL_STATES = ("assigned", "submitted")
_TRIAL_ARTIFACT_URL_TTL_SECONDS = 900


async def _load_open_trial(
    db: AsyncSession,
    *,
    org_id: UUID,
) -> tuple[OrgAttestorApplication, AttestorTrial]:
    """Load the org's live or latest trial, or raise 404 if none exist."""
    application = await db.scalar(
        select(OrgAttestorApplication).where(OrgAttestorApplication.org_id == org_id)
    )
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active trial.",
        )

    trial = await db.scalar(
        select(AttestorTrial)
        .where(
            AttestorTrial.org_application_id == application.id,
            AttestorTrial.status.in_(_OPEN_TRIAL_STATES),
        )
        .order_by(AttestorTrial.attempt.desc())
        .limit(1)
    )
    if trial is None:
        trial = await db.scalar(
            select(AttestorTrial)
            .where(AttestorTrial.org_application_id == application.id)
            .order_by(AttestorTrial.attempt.desc())
            .limit(1)
        )
    if trial is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active trial.",
        )
    return application, trial


async def load_nominee_trial(
    db: AsyncSession,
    *,
    org_id: UUID,
    member: OrgMember,
) -> NomineeTrialResponse:
    """Return the nominated member's active trial workspace view.

    Args:
        db: Async database session.
        org_id: Organization whose live trial is being loaded.
        member: The caller's membership row in that organization.

    Returns:
        Fixture metadata, presigned artifacts, rubric dimensions, and any
        already-saved nominee scores.

    Raises:
        HTTPException(404): No assigned or submitted trial exists.
        HTTPException(403): Caller is not the nominated trial member.
    """
    application, trial = await _load_open_trial(db, org_id=org_id)
    if member.id != application.trial_member_id:
        logger.bind(
            module="organizations",
            action="load_nominee_trial",
            user_id=str(member.user_id),
            org_id=str(org_id),
        ).warning("access_denied")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not the nominated trial member.",
        )

    framework = await db.scalar(
        select(Framework).where(Framework.id == trial.seeded_framework_id)
    )
    if framework is None or framework.calibration_review_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trial fixture missing.",
        )

    dimensions = (
        await db.scalars(
            select(AttestationRubricDimension)
            .where(
                AttestationRubricDimension.review_type
                == framework.calibration_review_type,
                AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
            )
            .order_by(AttestationRubricDimension.display_order.asc())
        )
    ).all()
    artifacts = (
        await db.scalars(
            select(Artifact)
            .where(Artifact.framework_id == framework.id)
            .order_by(Artifact.created_at.asc())
        )
    ).all()
    saved_scores = (
        await db.scalars(
            select(AttestorTrialRubricScore)
            .where(AttestorTrialRubricScore.trial_id == trial.id)
            .order_by(AttestorTrialRubricScore.created_at.asc())
        )
    ).all()
    settings = get_settings()

    return NomineeTrialResponse(
        trial_id=trial.id,
        status=trial.status,
        framework_name=framework.title,
        framework_summary=framework.description,
        artifacts=[
            TrialArtifactSchema(
                name=artifact.name,
                mime_type=artifact.mime_type,
                url=s3.storage.presigned_get(
                    settings.s3_artifacts_bucket,
                    artifact.clean_file_key or artifact.file_key,
                    _TRIAL_ARTIFACT_URL_TTL_SECONDS,
                ),
            )
            for artifact in artifacts
        ],
        dimensions=[
            TrialRubricDimensionSchema(
                dimension_id=dimension.id,
                key=dimension.key,
                label=dimension.label,
                display_order=dimension.display_order,
            )
            for dimension in dimensions
        ],
        saved_scores=[
            TrialScoreInput(
                dimension_id=score.dimension_id,
                score=score.score,
                comment=score.comment,
            )
            for score in saved_scores
        ],
        feedback=trial.feedback,
    )


async def submit_nominee_trial(
    db: AsyncSession,
    *,
    org_id: UUID,
    member: OrgMember,
    payload: TrialSubmitRequest,
) -> NomineeTrialResponse:
    """Persist nominee scores, grade the trial, and mark it submitted.

    Args:
        db: Async database session.
        org_id: Organization whose active trial is being submitted.
        member: The calling organization member.
        payload: One score row per rubric dimension.

    Returns:
        The refreshed nominee trial view in the submitted state.

    Raises:
        HTTPException(403): Caller is not the nominated trial member.
        HTTPException(404): No active trial or fixture exists.
        HTTPException(409): Trial is not currently assigned.
        HTTPException(422): Missing, duplicate, or unknown rubric dimensions.
    """
    member_id = member.id
    member_user_id = member.user_id
    application, trial = await _load_open_trial(db, org_id=org_id)
    if member_id != application.trial_member_id:
        logger.bind(
            module="organizations",
            action="submit_nominee_trial",
            user_id=str(member_user_id),
            org_id=str(org_id),
        ).warning("access_denied")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not the nominated trial member.",
        )
    if trial.status != "assigned":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Trial already submitted.",
        )

    framework = await db.scalar(
        select(Framework).where(Framework.id == trial.seeded_framework_id)
    )
    if framework is None or framework.calibration_review_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trial fixture missing.",
        )

    dimensions = (
        await db.scalars(
            select(AttestationRubricDimension)
            .where(
                AttestationRubricDimension.review_type
                == framework.calibration_review_type,
                AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
            )
            .order_by(AttestationRubricDimension.display_order.asc())
        )
    ).all()
    dimension_ids = {dimension.id for dimension in dimensions}
    submitted_scores = {score.dimension_id: score for score in payload.scores}
    if (
        len(submitted_scores) != len(payload.scores)
        or set(submitted_scores) != dimension_ids
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Every rubric dimension must be scored exactly once.",
        )

    answer_keys = (
        await db.scalars(
            select(AttestorTrialAnswerKey).where(
                AttestorTrialAnswerKey.framework_id == framework.id
            )
        )
    ).all()
    answer_key_map = {
        answer_key.dimension_id: (
            answer_key.expected_score,
            answer_key.tolerance,
        )
        for answer_key in answer_keys
    }
    if set(answer_key_map) != dimension_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Fixture answer key is incomplete.",
        )

    score_pct, auto_result = trial_scoring.grade(
        nominee_scores={
            dimension_id: submitted_scores[dimension_id].score
            for dimension_id in dimension_ids
        },
        answer_key=answer_key_map,
        weights={dimension.id: dimension.weight for dimension in dimensions},
    )

    trial_id = trial.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        locked_trial = await db.get(AttestorTrial, trial_id, with_for_update=True)
        assert locked_trial is not None
        if locked_trial.status != "assigned":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Trial already submitted.",
            )
        for score in payload.scores:
            db.add(
                AttestorTrialRubricScore(
                    trial_id=locked_trial.id,
                    dimension_id=score.dimension_id,
                    score=score.score,
                    comment=score.comment,
                )
            )
        locked_trial.status = "submitted"
        locked_trial.submitted_at = datetime.now(UTC)
        locked_trial.score_pct = score_pct
        locked_trial.auto_result = auto_result

    logger.bind(
        module="organizations",
        action="submit_nominee_trial",
        user_id=str(member_user_id),
        org_id=str(org_id),
        trial_id=str(trial_id),
    ).info("trial_submitted")
    refreshed_member = await db.get(OrgMember, member_id)
    assert refreshed_member is not None
    return await load_nominee_trial(db, org_id=org_id, member=refreshed_member)
