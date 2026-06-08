"""External web-rarity scoring for Artifact processing.

This step estimates whether extracted framework phrases appear widely on the
public web. It skips paid external search when internal rarity already shows a
near-duplicate inside Auracles.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import Decimal
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.redis import get_redis
from app.integrations.brave_search import BraveSearchError, search_web
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact, ArtifactRarityAudit
from app.workers.async_runner import run_async
from app.workers.celery_app import app

INTERNAL_RARITY_EXTERNAL_SEARCH_THRESHOLD = Decimal("0.7000")
EXTERNAL_RARITY_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
MAX_EXTERNAL_PHRASES = 8
MAX_BRAVE_RETURNED_HITS = 20
TOKEN_PATTERN = re.compile(r"\b[\w'-]+\b")


def _cache_key(phrase: str) -> str:
    """Return a stable Redis cache key for one external-rarity phrase."""
    digest = hashlib.sha256(phrase.encode("utf-8")).hexdigest()
    return f"external_rarity:phrase:{digest}"


def _tokenize(text: str) -> list[str]:
    """Normalize extracted text into words used for phrase windows."""
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


def select_external_phrases(
    text: str,
    top_terms: list[str],
    *,
    limit: int = MAX_EXTERNAL_PHRASES,
) -> list[str]:
    """Select high-signal 5-10 word phrases containing top TF-IDF terms."""
    tokens = _tokenize(text)
    top_term_set = {term.lower() for term in top_terms}
    if len(tokens) < 5 or not top_term_set:
        return []

    candidates: list[tuple[int, int, str]] = []
    for start_index in range(len(tokens) - 4):
        for size in range(5, min(10, len(tokens) - start_index) + 1):
            window = tokens[start_index : start_index + size]
            score = sum(1 for token in window if token in top_term_set)
            if score >= 2:
                candidates.append((-score, start_index, " ".join(window)))

    phrases: list[str] = []
    seen: set[str] = set()
    for _, _, phrase in sorted(candidates):
        if phrase in seen:
            continue
        seen.add(phrase)
        phrases.append(phrase)
        if len(phrases) == limit:
            break
    return phrases


def external_rarity_from_hits(hit_counts: list[int]) -> Decimal:
    """Map returned web-hit counts to a rarity score in the 0..1 range."""
    if not hit_counts:
        return Decimal("1.0000")
    average_hits = sum(hit_counts) / len(hit_counts)
    bounded_hits = min(MAX_BRAVE_RETURNED_HITS, max(0.0, average_hits))
    rarity = 1.0 - (math.log1p(bounded_hits) / math.log1p(MAX_BRAVE_RETURNED_HITS))
    return Decimal(str(rarity)).quantize(Decimal("0.0001"))


async def search_external_phrase(phrase: str) -> int:
    """Return cached or live Brave web hit count for one quoted phrase."""
    cache = get_redis()
    key = _cache_key(phrase)
    cached = await cache.get(key)
    if cached is not None:
        cached_text = cached.decode("utf-8") if isinstance(cached, bytes) else cached
        return int(json.loads(str(cached_text))["total_hits"])

    result = await search_web(f'"{phrase}"')
    await cache.setex(
        key,
        EXTERNAL_RARITY_CACHE_TTL_SECONDS,
        json.dumps({"total_hits": result.total_hits}),
    )
    return result.total_hits


async def _mark_external_unavailable(
    artifact_id: UUID,
    framework_id: UUID,
) -> None:
    """Record that external rarity is unavailable without blocking publish."""
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, artifact_id)
        if artifact is None:
            return
        artifact.external_rarity = None
        framework = await db.get(Framework, framework_id)
        if framework is not None:
            failure_reasons = dict(framework.pipeline_failure_reasons or {})
            failure_reasons["external_check"] = "unavailable"
            framework.pipeline_failure_reasons = failure_reasons
        await db.commit()


async def _compute_external_rarity_impl(artifact_id: str) -> dict[str, Any]:
    """Compute or skip external rarity for an Artifact."""
    parsed_artifact_id = UUID(artifact_id)
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}
        internal_rarity = artifact.internal_rarity
        framework_id = artifact.framework_id
        metadata = dict(artifact.metadata_vector or {})
        if (
            internal_rarity is not None
            and internal_rarity < INTERNAL_RARITY_EXTERNAL_SEARCH_THRESHOLD
        ):
            artifact.external_rarity = None
            rarity_audit = await db.scalar(
                select(ArtifactRarityAudit).where(
                    ArtifactRarityAudit.artifact_id == parsed_artifact_id
                )
            )
            if rarity_audit is None:
                db.add(
                    ArtifactRarityAudit(
                        artifact_id=parsed_artifact_id,
                        external_phrases_queried=[],
                        external_hit_counts=[],
                    )
                )
            else:
                rarity_audit.external_phrases_queried = []
                rarity_audit.external_hit_counts = []
            await db.commit()
            return {
                "artifact_id": artifact_id,
                "status": "external_rarity_skipped",
                "reason": "internal_duplicate",
            }

    extraction = metadata.get("extraction", {})
    text = str(extraction.get("text", ""))
    top_terms = metadata.get("top_tfidf_terms", [])
    phrases = select_external_phrases(
        text,
        [str(term) for term in top_terms] if isinstance(top_terms, list) else [],
    )
    if not phrases:
        return {
            "artifact_id": artifact_id,
            "status": "external_rarity_skipped",
            "reason": "no_searchable_phrases",
        }

    try:
        hit_counts = [await search_external_phrase(phrase) for phrase in phrases]
    except (BraveSearchError, RuntimeError, ValueError, LookupError) as exc:
        logger.bind(
            module="artifacts",
            action="compute_external_rarity",
            artifact_id=artifact_id,
        ).warning("external_rarity_unavailable", error=str(exc))
        await _mark_external_unavailable(parsed_artifact_id, framework_id)
        return {
            "artifact_id": artifact_id,
            "status": "external_rarity_unavailable",
        }

    external_rarity = external_rarity_from_hits(hit_counts)
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}
        artifact.external_rarity = external_rarity
        rarity_audit = await db.scalar(
            select(ArtifactRarityAudit).where(
                ArtifactRarityAudit.artifact_id == parsed_artifact_id
            )
        )
        if rarity_audit is None:
            db.add(
                ArtifactRarityAudit(
                    artifact_id=parsed_artifact_id,
                    external_phrases_queried=phrases,
                    external_hit_counts=hit_counts,
                )
            )
        else:
            rarity_audit.external_phrases_queried = phrases
            rarity_audit.external_hit_counts = hit_counts
        await db.commit()

    return {
        "artifact_id": artifact_id,
        "status": "external_rarity_computed",
        "external_rarity": float(external_rarity),
    }


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def compute_external_rarity(self: Any, artifact_id: str) -> dict[str, Any]:
    """Celery wrapper for external rarity scoring."""
    log = logger.bind(
        module="artifacts",
        action="compute_external_rarity",
        task_id=self.request.id,
        artifact_id=artifact_id,
    )
    log.info("task_started")
    try:
        result = run_async(_compute_external_rarity_impl(artifact_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
