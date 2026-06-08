"""Framework-level pipeline gate evaluation.

Artifact workers own per-file processing fields. This module rolls those fields
up into the Framework state machine so publishing depends on every current
Artifact being clean, processed, and free of hard-blocking trust issues.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact, ArtifactRarityAudit

INTERNAL_RARITY_HARD_FAIL_THRESHOLD = Decimal("0.3000")
EXTERNAL_RARITY_SOFT_FAIL_THRESHOLD = Decimal("0.3000")
GATED_FRAMEWORK_STATUSES = {"submitted", "processing", "pipeline_failed"}


async def _soft_fail_acknowledged(db: AsyncSession, artifact_id: UUID) -> bool:
    """Return whether a Contributor acknowledged external rarity risk."""
    audit = await db.scalar(
        select(ArtifactRarityAudit).where(
            ArtifactRarityAudit.artifact_id == artifact_id,
            ArtifactRarityAudit.soft_fail_acknowledged.is_(True),
        )
    )
    return audit is not None


async def evaluate_framework_pipeline(
    db: AsyncSession,
    framework: Framework,
    *,
    force: bool = False,
) -> Framework:
    """Update Framework pipeline status from all current Artifact states."""
    if not force and framework.status not in GATED_FRAMEWORK_STATUSES:
        return framework

    artifacts = (
        await db.execute(
            select(Artifact)
            .where(
                Artifact.framework_id == framework.id,
                Artifact.current_for_framework.is_(True),
            )
            .order_by(Artifact.created_at)
        )
    ).scalars().all()

    if not artifacts:
        framework.status = "pipeline_failed"
        framework.pipeline_failure_reasons = {
            "artifacts": "At least one Artifact is required."
        }
        framework.last_pipeline_run_at = datetime.now(UTC)
        return framework

    waiting = False
    failure_reasons: dict[str, Any] = {}
    for artifact in artifacts:
        artifact_key = str(artifact.id)
        if artifact.scan_status == "infected":
            failure_reasons.setdefault("virus", []).append(artifact_key)
        elif artifact.scan_status == "error":
            failure_reasons.setdefault("scan_error", []).append(artifact_key)

        if artifact.processing_status in {"pending", "processing"}:
            waiting = True
        elif artifact.processing_status == "failed":
            failure_reasons.setdefault("processing", []).append(artifact_key)
        elif artifact.processing_status == "flagged_pii":
            failure_reasons.setdefault("pii", []).append(artifact_key)

        if artifact.pii_review_needed:
            failure_reasons.setdefault("pii", []).append(artifact_key)
        if (
            artifact.internal_rarity is not None
            and artifact.internal_rarity < INTERNAL_RARITY_HARD_FAIL_THRESHOLD
        ):
            failure_reasons.setdefault("internal_rarity", []).append(artifact_key)
        if (
            artifact.external_rarity is not None
            and artifact.external_rarity < EXTERNAL_RARITY_SOFT_FAIL_THRESHOLD
            and not await _soft_fail_acknowledged(db, artifact.id)
        ):
            failure_reasons.setdefault("external_rarity", []).append(artifact_key)

    existing_reasons = dict(framework.pipeline_failure_reasons or {})
    if existing_reasons.get("external_check") == "unavailable":
        failure_reasons["external_check"] = "unavailable"

    framework.last_pipeline_run_at = datetime.now(UTC)
    if failure_reasons:
        framework.status = "pipeline_failed"
        framework.pipeline_failure_reasons = failure_reasons
    elif waiting:
        framework.status = "processing"
        framework.pipeline_failure_reasons = {}
    else:
        framework.status = "pipeline_passed"
        framework.pipeline_failure_reasons = {}
    return framework


async def evaluate_framework_pipeline_for_artifact(artifact_id: str) -> dict[str, Any]:
    """Evaluate the parent Framework after one Artifact pipeline completes."""
    parsed_artifact_id = UUID(artifact_id)
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}
        framework = await db.get(Framework, artifact.framework_id)
        if framework is None:
            return {"artifact_id": artifact_id, "status": "missing_framework"}
        await evaluate_framework_pipeline(db, framework)
        await db.commit()
        return {
            "artifact_id": artifact_id,
            "framework_id": str(framework.id),
            "framework_status": framework.status,
        }
