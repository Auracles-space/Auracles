"""Metadata enrichment step for Artifact processing.

This step turns extracted text into compact, queryable signals used by later
rarity, recommendation, and search slices.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from langdetect import (  # type: ignore[import-untyped]
    DetectorFactory,
    LangDetectException,
    detect,
)
from loguru import logger
from sklearn.feature_extraction.text import (
    TfidfVectorizer,  # type: ignore[import-untyped]
)

from app.core.database import async_session_factory
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.workers.async_runner import run_async
from app.workers.celery_app import app

DetectorFactory.seed = 0
TOP_TERM_LIMIT = 20


def _detect_language(text: str) -> str:
    """Return a stable language code for extracted text."""
    if len(text.strip()) < 20:
        return "unknown"
    try:
        return str(detect(text))
    except LangDetectException:
        return "unknown"


def _top_tfidf_terms(text: str) -> list[str]:
    """Return the highest-scoring single-word TF-IDF terms for one artifact."""
    if not text.strip():
        return []
    vectorizer = TfidfVectorizer(
        stop_words="english",
        lowercase=True,
        ngram_range=(1, 1),
        max_features=100,
    )
    try:
        matrix = vectorizer.fit_transform([text])
    except ValueError:
        return []
    scores = matrix.toarray()[0]
    terms = vectorizer.get_feature_names_out()
    ranked = sorted(
        zip(terms, scores, strict=True),
        key=lambda item: (-item[1], item[0]),
    )
    return [term for term, score in ranked[:TOP_TERM_LIMIT] if score > 0]


def _overlapping_tags(text: str, framework_tags: list[str]) -> list[str]:
    """Return Framework tags that appear in extracted artifact text."""
    lower_text = text.lower()
    return [
        normalized_tag
        for tag in framework_tags
        if (normalized_tag := str(tag).strip().lower()) and normalized_tag in lower_text
    ]


def _metadata_payload(
    metadata: dict[str, Any],
    framework_tags: list[str],
) -> dict[str, Any]:
    """Build the Slice 5 metadata additions from existing extraction output."""
    extraction = metadata.get("extraction", {})
    text = str(extraction.get("text", ""))
    headings = extraction.get("headings", [])
    top_terms = _top_tfidf_terms(text)
    overlapping_tags = _overlapping_tags(text, framework_tags)
    return {
        "language": _detect_language(text),
        "char_count": len(text),
        "top_tfidf_terms": top_terms,
        "n_headings": len(headings) if isinstance(headings, list) else 0,
        "n_tables": int(extraction.get("table_count", 0) or 0),
        "n_images": int(extraction.get("image_count", 0) or 0),
        "word_count": int(extraction.get("word_count", 0) or 0),
        "tag_overlap_count": len(overlapping_tags),
        "tag_overlap_tags": overlapping_tags,
    }


async def _compute_metadata_impl(artifact_id: str) -> dict[str, Any]:
    """Complete metadata_vector fields for an Artifact."""
    parsed_artifact_id = UUID(artifact_id)
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}
        framework = await db.get(Framework, artifact.framework_id)
        framework_tags = list(framework.tags) if framework else []
        metadata = dict(artifact.metadata_vector or {})
        metadata.update(_metadata_payload(metadata, framework_tags))
        artifact.metadata_vector = metadata
        await db.commit()
    return {"artifact_id": artifact_id, "status": "metadata_computed"}


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def compute_metadata(self: Any, artifact_id: str) -> dict[str, Any]:
    """Celery wrapper for Artifact metadata enrichment."""
    log = logger.bind(
        module="artifacts",
        action="compute_metadata",
        task_id=self.request.id,
        artifact_id=artifact_id,
    )
    log.info("task_started")
    try:
        result = run_async(_compute_metadata_impl(artifact_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
