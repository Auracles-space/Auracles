"""PII detection and redaction step for Artifact processing.

This module reads extracted text from `metadata_vector`, records a PII audit
row, and pauses processing when any PII is found.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import delete

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.modules.frameworks.models_artifact import Artifact, ArtifactPiiAudit
from app.workers.async_runner import run_async
from app.workers.celery_app import app

PII_CONFIDENCE_THRESHOLD = 0.6


@dataclass(frozen=True)
class PiiFinding:
    """Normalized PII finding returned by the detection adapter."""

    entity_type: str
    score: float
    start: int
    end: int


def _build_analyzer() -> Any:
    """Construct a Presidio AnalyzerEngine.

    This loads the spaCy ``en_core_web_lg`` model (hundreds of MB of RAM) and is
    therefore expensive — call it once per process via :func:`_get_analyzer`.
    """
    from presidio_analyzer import AnalyzerEngine

    return AnalyzerEngine()


@lru_cache(maxsize=1)
def _get_analyzer() -> Any:
    """Return a process-cached Presidio analyzer.

    Building the engine per task reloaded the spaCy model on every artifact and,
    multiplied by Celery worker concurrency, exhausted worker memory (OOM
    restarts on Render). Caching one instance per worker process keeps the model
    resident and bounded.
    """
    return _build_analyzer()


def detect_pii_from_text(text: str) -> list[PiiFinding]:
    """Detect PII in extracted text with Presidio Analyzer."""
    analyzer = _get_analyzer()
    results = analyzer.analyze(text=text, language="en")
    return [
        PiiFinding(
            entity_type=result.entity_type,
            score=float(result.score),
            start=int(result.start),
            end=int(result.end),
        )
        for result in results
    ]


def _unique_entity_types(findings: list[PiiFinding]) -> list[str]:
    """Return sorted unique PII entity types for audit storage."""
    return sorted({finding.entity_type for finding in findings})


async def _detect_pii_impl(artifact_id: str) -> dict[str, Any]:
    """Detect PII from extracted text and persist Artifact/audit state."""
    parsed_artifact_id = UUID(artifact_id)
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}
        metadata = artifact.metadata_vector or {}
        extraction = metadata.get("extraction", {})
        text = str(extraction.get("text", ""))

    findings = detect_pii_from_text(text) if text else []
    high_confidence = [
        finding for finding in findings if finding.score >= PII_CONFIDENCE_THRESHOLD
    ]
    review_needed = bool(findings)

    entity_types = _unique_entity_types(findings)
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}

        artifact.pii_detected = bool(high_confidence)
        artifact.pii_review_needed = review_needed
        artifact.clean_file_key = None
        if review_needed:
            artifact.processing_status = "flagged_pii"

        await db.execute(
            delete(ArtifactPiiAudit).where(
                ArtifactPiiAudit.artifact_id == parsed_artifact_id
            )
        )
        db.add(
            ArtifactPiiAudit(
                artifact_id=parsed_artifact_id,
                pii_types_found=entity_types,
                auto_redacted=False,
                flagged_for_review=review_needed,
            )
        )
        if findings:
            await write_audit(
                db=db,
                actor_id=None,
                action="artifact_pii_flagged",
                target_type="artifact",
                target_id=artifact.id,
                metadata={
                    "framework_id": str(artifact.framework_id),
                    "pii_types_found": entity_types,
                    "high_confidence": bool(high_confidence),
                    "auto_redacted": False,
                    "flagged_for_review": review_needed,
                },
            )
        await db.commit()

    if review_needed:
        return {"artifact_id": artifact_id, "status": "flagged_pii"}
    return {"artifact_id": artifact_id, "status": "clear"}


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def detect_pii(self: Any, artifact_id: str) -> dict[str, Any]:
    """Celery wrapper for Artifact PII detection."""
    log = logger.bind(
        module="artifacts",
        action="detect_pii",
        task_id=self.request.id,
        artifact_id=artifact_id,
    )
    log.info("task_started")
    try:
        result = run_async(_detect_pii_impl(artifact_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
