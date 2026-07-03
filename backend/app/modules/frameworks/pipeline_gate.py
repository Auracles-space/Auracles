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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.modules.frameworks.models import Framework, Review
from app.modules.frameworks.models_artifact import Artifact, ArtifactRarityAudit

NEAR_DUPLICATE_JACCARD_THRESHOLD = Decimal("0.9000")
SIMILARITY_NOTICE_JACCARD_THRESHOLD = Decimal("0.7000")
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


async def _rarity_audit(
    db: AsyncSession,
    artifact_id: UUID,
) -> ArtifactRarityAudit | None:
    """Return the rarity audit row for one Artifact when present."""
    audit: ArtifactRarityAudit | None = await db.scalar(
        select(ArtifactRarityAudit).where(
            ArtifactRarityAudit.artifact_id == artifact_id
        )
    )
    return audit


def _internal_jaccard(
    artifact: Artifact,
    audit: ArtifactRarityAudit | None,
) -> Decimal | None:
    """Return copy-oriented internal Jaccard for band evaluation."""
    if audit is not None and audit.internal_jaccard is not None:
        return audit.internal_jaccard
    if artifact.internal_rarity is None:
        return None
    return Decimal("1.0000") - artifact.internal_rarity


async def _similarity_notice(
    db: AsyncSession,
    audit: ArtifactRarityAudit | None,
    jaccard: Decimal,
) -> dict[str, Any]:
    """Build public, non-blocking similarity context for an Artifact."""
    nearest_match_artifact_id = None
    nearest_match_framework_id = None
    nearest_match_title = None
    average_review_score = None
    review_count = 0
    if audit is not None and audit.nearest_match_id is not None:
        nearest_match_artifact_id = audit.nearest_match_id
        nearest = await db.execute(
            select(Artifact, Framework)
            .join(Framework, Framework.id == Artifact.framework_id)
            .where(Artifact.id == audit.nearest_match_id)
        )
        nearest_row = nearest.first()
        if nearest_row is not None:
            _, nearest_framework = nearest_row
            nearest_match_framework_id = nearest_framework.id
            nearest_match_title = nearest_framework.title
            aggregate = await db.execute(
                select(func.avg(Review.score), func.count(Review.id)).where(
                    Review.framework_id == nearest_framework.id
                )
            )
            average_score, count = aggregate.one()
            review_count = int(count or 0)
            if average_score is not None:
                average_review_score = str(
                    Decimal(average_score).quantize(Decimal("0.01"))
                )
    return {
        "jaccard": str(jaccard.quantize(Decimal("0.0001"))),
        "nearest_match_artifact_id": (
            str(nearest_match_artifact_id) if nearest_match_artifact_id else None
        ),
        "nearest_match_framework_id": (
            str(nearest_match_framework_id) if nearest_match_framework_id else None
        ),
        "nearest_match_title": nearest_match_title,
        "average_review_score": average_review_score,
        "review_count": review_count,
    }


async def _apply_similarity_band(
    db: AsyncSession,
    artifact: Artifact,
    audit: ArtifactRarityAudit | None,
    failure_reasons: dict[str, Any],
) -> None:
    """Apply near-duplicate hard block or non-blocking notice to an Artifact."""
    metadata = dict(artifact.metadata_vector or {})
    metadata.pop("similarity_notice", None)
    metadata.pop("near_duplicate_blocked", None)
    jaccard = _internal_jaccard(artifact, audit)
    if jaccard is None:
        artifact.metadata_vector = metadata
        return
    overridden = audit is not None and audit.near_duplicate_overridden_at is not None
    if jaccard >= NEAR_DUPLICATE_JACCARD_THRESHOLD and not overridden:
        failure_reasons.setdefault("internal_rarity", []).append(str(artifact.id))
        metadata["near_duplicate_blocked"] = True
    elif jaccard >= SIMILARITY_NOTICE_JACCARD_THRESHOLD:
        metadata["similarity_notice"] = await _similarity_notice(db, audit, jaccard)
    artifact.metadata_vector = metadata


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
        (
            await db.execute(
                select(Artifact)
                .where(
                    Artifact.framework_id == framework.id,
                    Artifact.current_for_framework.is_(True),
                )
                .order_by(Artifact.created_at)
            )
        )
        .scalars()
        .all()
    )

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
        rarity_audit = await _rarity_audit(db, artifact.id)
        await _apply_similarity_band(db, artifact, rarity_audit, failure_reasons)
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
