"""Org Attestor calibration-trial service.

Provides the nominee-facing trial workspace loader used by the member-scoped
trial page. Trial grading and admin decisioning are layered in later slices.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations import s3
from app.modules.attestation import rubrics
from app.modules.attestation.models import (
    AttestationRubricDimension,
    AttestorTrial,
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
)

_OPEN_TRIAL_STATES = ("assigned", "submitted")
_TRIAL_ARTIFACT_URL_TTL_SECONDS = 900


async def _load_open_trial(
    db: AsyncSession,
    *,
    org_id: UUID,
) -> tuple[OrgAttestorApplication, AttestorTrial]:
    """Load the org's live application plus latest active trial, or raise 404."""
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
