"""Final rarity blend step for Artifact processing.

This step combines internal rarity, external web rarity, and a small metadata
uplift into the single `artifacts.rarity_score` displayed and gated later.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.frameworks.models_artifact import Artifact, ArtifactRarityAudit
from app.workers.async_runner import run_async
from app.workers.celery_app import app

DECIMAL_4_PLACES = Decimal("0.0001")
NEUTRAL_EXTERNAL_RARITY = Decimal("0.5000")


def _decimal_score(value: Decimal) -> Decimal:
    """Clamp and quantize a rarity score for NUMERIC(5,4) columns."""
    bounded = min(Decimal("1.0000"), max(Decimal("0.0000"), value))
    return bounded.quantize(DECIMAL_4_PLACES, rounding=ROUND_HALF_UP)


def _metadata_uplift(_: Artifact) -> Decimal:
    """Return the current metadata rarity uplift.

    Slice 7 stores the audit field and keeps the MVP implementation neutral.
    Later catalog-density logic can replace this without changing the blend API.
    """
    return Decimal("0.0000")


def blend_rarity_score(
    internal_rarity: Decimal,
    external_rarity: Decimal | None,
    metadata_uplift: Decimal,
) -> Decimal:
    """Blend rarity inputs into the final marketplace rarity score."""
    if external_rarity is None:
        return _decimal_score(
            (Decimal("0.625") * internal_rarity)
            + (Decimal("0.125") * metadata_uplift)
            + (Decimal("0.250") * NEUTRAL_EXTERNAL_RARITY)
        )
    return _decimal_score(
        (Decimal("0.500") * internal_rarity)
        + (Decimal("0.400") * external_rarity)
        + (Decimal("0.100") * metadata_uplift)
    )


async def _compute_final_rarity_impl(artifact_id: str) -> dict[str, Any]:
    """Persist final rarity score and update the rarity audit row."""
    parsed_artifact_id = UUID(artifact_id)
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}
        if artifact.internal_rarity is None:
            return {"artifact_id": artifact_id, "status": "missing_internal_rarity"}

        metadata_uplift = _metadata_uplift(artifact)
        rarity_score = blend_rarity_score(
            artifact.internal_rarity,
            artifact.external_rarity,
            metadata_uplift,
        )
        artifact.rarity_score = rarity_score
        artifact.processing_status = "processed"

        rarity_audit = await db.scalar(
            select(ArtifactRarityAudit).where(
                ArtifactRarityAudit.artifact_id == parsed_artifact_id
            )
        )
        if rarity_audit is None:
            db.add(
                ArtifactRarityAudit(
                    artifact_id=parsed_artifact_id,
                    metadata_uplift=metadata_uplift,
                    blended_score=rarity_score,
                )
            )
        else:
            rarity_audit.metadata_uplift = metadata_uplift
            rarity_audit.blended_score = rarity_score
        await db.commit()

    return {
        "artifact_id": artifact_id,
        "framework_id": str(artifact.framework_id),
        "status": "final_rarity_computed",
        "rarity_score": float(rarity_score),
    }


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def compute_final_rarity(self: Any, artifact_id: str) -> dict[str, Any]:
    """Celery wrapper for final Artifact rarity scoring."""
    log = logger.bind(
        module="artifacts",
        action="compute_final_rarity",
        task_id=self.request.id,
        artifact_id=artifact_id,
    )
    log.info("task_started")
    try:
        result = run_async(_compute_final_rarity_impl(artifact_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
