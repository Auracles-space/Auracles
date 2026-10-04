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
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact, ArtifactPiiAudit
from app.modules.organizations import notifications as org_notifications
from app.workers.async_runner import run_async
from app.workers.celery_app import app
from app.workers.tasks.project_notifications import dispatch_project_notification

PII_CONFIDENCE_THRESHOLD = 0.6

# Only genuinely sensitive entity types block publishing. Presidio also emits
# entities that routinely appear in legitimate framework prose — most notably
# DATE_TIME ("30 days", "Day 30"), plus URL and NRP — which must never fail the
# gate or no knowledge artifact could ever pass. Contact details, financial and
# government identifiers, names, and locations are the publishable-data risks we
# actually guard against.
BLOCKING_PII_ENTITY_TYPES = frozenset(
    {
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CREDIT_CARD",
        "CRYPTO",
        "IBAN_CODE",
        "US_SSN",
        "US_ITIN",
        "US_BANK_NUMBER",
        "US_PASSPORT",
        "US_DRIVER_LICENSE",
        "MEDICAL_LICENSE",
        "PERSON",
        "LOCATION",
    }
)


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


def pii_override_accepted(metadata: dict[str, Any] | None) -> bool:
    """Whether the owner has declared this artifact's matches to be citations.

    The detector cannot tell an institution from a person: "Central Bank of
    Nigeria" reads as a PERSON or LOCATION, so a document whose purpose is
    citing an agency is held, and the only way through — redaction — removes
    the very name the document exists to quote.

    An override waives the hold. It never suppresses the finding: the scan
    still records the entity types so an admin reviewing the override can see
    exactly what was waved through, and by whom.

    Args:
        metadata: The artifact's metadata vector, or None.

    Returns:
        True when an accepted override is recorded.
    """
    override = (metadata or {}).get("pii_override") or {}
    return bool(override.get("accepted"))


def select_blocking_findings(findings: list[PiiFinding]) -> list[PiiFinding]:
    """Return findings that should block publishing.

    A finding blocks only when it is a sensitive entity type
    (:data:`BLOCKING_PII_ENTITY_TYPES`) and meets
    :data:`PII_CONFIDENCE_THRESHOLD`. Benign entities (DATE_TIME, URL, ...) and
    low-confidence guesses are ignored so ordinary framework content can pass.
    """
    return [
        finding
        for finding in findings
        if finding.score >= PII_CONFIDENCE_THRESHOLD
        and finding.entity_type in BLOCKING_PII_ENTITY_TYPES
    ]


async def _notify_owner_of_pii_hold(db: Any, artifact: Artifact) -> None:
    """Tell whoever owns the framework that their artifact is held.

    Only the owner can clear a PII hold — the admin queue shows the row but
    offers nothing to click, because accepting the redaction is a contributor
    action. Before this, nothing said so: the framework stopped short of
    publishing, the owner's profile still counted it, and the artifact was
    simply invisible. QA reported it as a missing framework with no button.

    The detected entity types are deliberately not in the body. A notification
    reaches email and would carry the sensitive categories out of the product;
    the framework workspace names them in place.
    """
    framework = await db.get(Framework, artifact.framework_id)
    if framework is None:
        return
    if framework.contributor_org_id is not None:
        recipients = await org_notifications.org_owner_ids(
            db, framework.contributor_org_id
        )
    elif framework.contributor_id is not None:
        recipients = [framework.contributor_id]
    else:
        recipients = []
    for recipient in recipients:
        dispatch_project_notification.delay(
            user_id=str(recipient),
            notification_type="artifact_pii_review_required",
            title="An upload needs your review before publishing",
            body=(
                f"{artifact.name} in {framework.title} contains information "
                "that has to be removed or accepted before the framework can "
                "be published. Open the framework to see what was found."
            ),
            link=f"/dashboard/frameworks/{framework.id}",
            payload={
                "framework_id": str(framework.id),
                "artifact_id": str(artifact.id),
            },
            dedupe_key=f"artifact_pii_review:{artifact.id}",
        )


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
    blocking = select_blocking_findings(findings)
    # The scan always runs and always records what it found. An override only
    # waives the hold, so re-processing an artifact whose owner declared its
    # matches to be citations does not strand it again on the same names.
    overridden = pii_override_accepted(metadata)
    review_needed = bool(blocking) and not overridden

    # Audit records the sensitive types that triggered review, not every benign
    # entity Presidio emitted, so the contributor-facing reason is meaningful.
    entity_types = _unique_entity_types(blocking)
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}

        # Detected and held are different facts: an overridden artifact still
        # carries matches, and an admin reviewing the override needs to see so.
        artifact.pii_detected = bool(blocking)
        artifact.pii_review_needed = review_needed
        artifact.clean_file_key = None
        if review_needed:
            artifact.processing_status = "flagged_pii"

        # Persist the blocking types on the artifact so the contributor-facing
        # response can name exactly what to remove (audit row is not joined in
        # the read path).
        updated_metadata = dict(artifact.metadata_vector or {})
        updated_metadata["pii_review_types"] = entity_types
        artifact.metadata_vector = updated_metadata

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
        if blocking:
            await write_audit(
                db=db,
                actor_id=None,
                action="artifact_pii_flagged",
                target_type="artifact",
                target_id=artifact.id,
                metadata={
                    "framework_id": str(artifact.framework_id),
                    "pii_types_found": entity_types,
                    "auto_redacted": False,
                    "flagged_for_review": review_needed,
                    "citation_override": overridden,
                },
            )
        await db.commit()
        if blocking:
            # After commit: the notification points at a framework whose held
            # state must already be readable when the owner follows the link.
            await _notify_owner_of_pii_hold(db, artifact)

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
