"""Internal rarity scoring for Artifact processing."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import delete, select

from app.core.database import async_session_factory
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact, ArtifactRarityAudit
from app.workers.async_runner import run_async
from app.workers.celery_app import app
from app.workers.tasks.processing.minhash import minhash_from_signature

DECIMAL_4_PLACES = Decimal("0.0001")


def _decimal_score(value: float) -> Decimal:
    """Convert a float similarity score into NUMERIC(5,4)-safe Decimal."""
    bounded = min(1.0, max(0.0, value))
    return Decimal(str(bounded)).quantize(DECIMAL_4_PLACES, rounding=ROUND_HALF_UP)


async def _published_candidates(
    artifact_id: UUID,
) -> list[tuple[UUID, bytes]]:
    """Return published artifact signatures eligible for internal comparison."""
    async with async_session_factory() as db:
        rows = await db.execute(
            select(Artifact.id, Artifact.minhash_signature)
            .join(Framework, Framework.id == Artifact.framework_id)
            .where(
                Artifact.id != artifact_id,
                Artifact.minhash_signature.is_not(None),
                Framework.status == "published",
            )
        )
        return [
            (candidate_id, signature)
            for candidate_id, signature in rows.all()
            if signature is not None
        ]


async def _compute_internal_rarity_impl(artifact_id: str) -> dict[str, Any]:
    """Compare an Artifact against published signatures and persist rarity."""
    parsed_artifact_id = UUID(artifact_id)
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}
        signature = artifact.minhash_signature
        if signature is None:
            return {"artifact_id": artifact_id, "status": "missing_signature"}
        metadata = dict(artifact.metadata_vector or {})
        minhash_metadata = metadata.get("minhash", {})
        shingle_count = int(minhash_metadata.get("shingle_count", 0) or 0)

    if shingle_count == 0:
        async with async_session_factory() as db:
            artifact = await db.get(Artifact, parsed_artifact_id)
            if artifact is None:
                return {"artifact_id": artifact_id, "status": "missing"}
            artifact.internal_rarity = Decimal("1.0000")
            artifact.nearest_match_id = None
            await db.execute(
                delete(ArtifactRarityAudit).where(
                    ArtifactRarityAudit.artifact_id == parsed_artifact_id
                )
            )
            db.add(
                ArtifactRarityAudit(
                    artifact_id=parsed_artifact_id,
                    internal_jaccard=Decimal("0.0000"),
                    nearest_match_id=None,
                )
            )
            await db.commit()
        return {
            "artifact_id": artifact_id,
            "status": "internal_rarity_computed",
            "internal_rarity": 1.0,
            "max_jaccard": 0.0,
            "nearest_match_id": None,
        }

    current_minhash = minhash_from_signature(signature)
    nearest_match_id: UUID | None = None
    max_jaccard = 0.0
    for candidate_id, candidate_signature in await _published_candidates(
        parsed_artifact_id
    ):
        candidate_minhash = minhash_from_signature(candidate_signature)
        jaccard = float(current_minhash.jaccard(candidate_minhash))
        if jaccard > max_jaccard:
            max_jaccard = jaccard
            nearest_match_id = candidate_id

    internal_rarity = 1.0 - max_jaccard
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}
        artifact.internal_rarity = _decimal_score(internal_rarity)
        artifact.nearest_match_id = nearest_match_id
        await db.execute(
            delete(ArtifactRarityAudit).where(
                ArtifactRarityAudit.artifact_id == parsed_artifact_id
            )
        )
        db.add(
            ArtifactRarityAudit(
                artifact_id=parsed_artifact_id,
                internal_jaccard=_decimal_score(max_jaccard),
                nearest_match_id=nearest_match_id,
            )
        )
        await db.commit()

    return {
        "artifact_id": artifact_id,
        "status": "internal_rarity_computed",
        "internal_rarity": float(_decimal_score(internal_rarity)),
        "max_jaccard": float(_decimal_score(max_jaccard)),
        "nearest_match_id": str(nearest_match_id) if nearest_match_id else None,
    }


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def compute_internal_rarity(self: Any, artifact_id: str) -> dict[str, Any]:
    """Celery wrapper for internal rarity scoring."""
    log = logger.bind(
        module="artifacts",
        action="compute_internal_rarity",
        task_id=self.request.id,
        artifact_id=artifact_id,
    )
    log.info("task_started")
    try:
        result = run_async(_compute_internal_rarity_impl(artifact_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
