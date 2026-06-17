"""Format-preserving redaction step for PII-flagged Artifacts.

This module generates private review copies for Artifacts whose extracted text
contains PII. The original object remains private; `clean_file_key` points to a
new redacted object only after generation and virus scanning succeed.
"""

from __future__ import annotations

import tempfile
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4
from xml.etree import ElementTree

from loguru import logger
from sqlalchemy import select

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.frameworks.models_artifact import Artifact, ArtifactPiiAudit
from app.workers.async_runner import run_async
from app.workers.celery_app import app
from app.workers.tasks.processing.pii import PiiFinding, detect_pii_from_text

OFFICE_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
PDF_MIME_TYPE = "application/pdf"
REDACTION_TOKEN = "[REDACTED]"


class RedactionError(RuntimeError):
    """Raised when a redacted review copy cannot be safely generated."""


def _pii_values(text: str) -> tuple[list[PiiFinding], list[str]]:
    """Return PII findings and exact values without persisting raw PII."""
    findings = detect_pii_from_text(text) if text else []
    values = sorted(
        {
            text[finding.start : finding.end].strip()
            for finding in findings
            if text[finding.start : finding.end].strip()
        },
        key=len,
        reverse=True,
    )
    return findings, values


def _redact_text(text: str | None, values: list[str]) -> str | None:
    """Replace detected PII values in one XML text node."""
    if text is None:
        return None
    redacted = text
    for value in values:
        redacted = redacted.replace(value, REDACTION_TOKEN)
    return redacted


def _is_safe_zip_member(name: str) -> bool:
    """Return whether a ZIP member path is safe to copy into output."""
    normalized = name.replace("\\", "/")
    member_path = PurePosixPath(normalized)
    return not member_path.is_absolute() and ".." not in member_path.parts


def redact_office_package(source_bytes: bytes, values: list[str]) -> bytes:
    """Rewrite Office XML text nodes while preserving the package structure."""
    if not values:
        raise RedactionError("No PII values were available for Office redaction.")

    output = BytesIO()
    with zipfile.ZipFile(BytesIO(source_bytes)) as source:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                if not _is_safe_zip_member(info.filename):
                    raise RedactionError(
                        f"Unsafe Office package member: {info.filename}"
                    )
                body = source.read(info)
                if info.filename.lower().endswith(".xml"):
                    try:
                        root = ElementTree.fromstring(body)
                    except ElementTree.ParseError:
                        target.writestr(info, body)
                        continue
                    for node in root.iter():
                        node.text = _redact_text(node.text, values)
                        node.tail = _redact_text(node.tail, values)
                    body = ElementTree.tostring(
                        root,
                        encoding="utf-8",
                        xml_declaration=True,
                    )
                target.writestr(info, body)
    redacted = output.getvalue()
    for value in values:
        if value.encode("utf-8") in redacted:
            raise RedactionError("Office redaction left PII bytes in the output.")
    return redacted


def redact_pdf_bytes(source_bytes: bytes, values: list[str]) -> bytes:
    """Apply real PDF redaction annotations and remove original PII bytes."""
    if not values:
        raise RedactionError("No PII values were available for PDF redaction.")

    import fitz

    document = fitz.open(stream=source_bytes, filetype="pdf")
    redaction_count = 0
    for page in document:
        for value in values:
            for rect in page.search_for(value):
                page.add_redact_annot(
                    rect,
                    text=REDACTION_TOKEN,
                    fill=(1, 1, 1),
                    text_color=(0, 0, 0),
                )
                redaction_count += 1
        page.apply_redactions()

    if redaction_count == 0:
        raise RedactionError("PDF redaction could not locate detected PII text.")

    redacted = bytes(document.tobytes(garbage=4, deflate=True, clean=True))
    document.close()
    for value in values:
        if value.encode("utf-8") in redacted:
            raise RedactionError("PDF redaction left PII bytes in the output.")
    return redacted


def redact_file_bytes(source_bytes: bytes, mime_type: str, values: list[str]) -> bytes:
    """Return redacted bytes for a supported Artifact MIME type."""
    if mime_type == PDF_MIME_TYPE:
        return redact_pdf_bytes(source_bytes, values)
    if mime_type in OFFICE_MIME_TYPES:
        return redact_office_package(source_bytes, values)
    raise RedactionError(f"Redaction is unsupported for MIME type {mime_type}.")


def scan_file_for_virus(path: str) -> str:
    """Scan a generated redacted file before it can become a clean object."""
    from app.workers.tasks.artifacts import scan_file_with_clamav

    return scan_file_with_clamav(path)


def _redacted_key(artifact: Artifact) -> str:
    """Build a private S3 key for a redacted review copy."""
    suffix = artifact.name.rsplit(".", 1)[-1].lower() if "." in artifact.name else "bin"
    return (
        f"frameworks/{artifact.framework_id}/artifacts/{artifact.id}/"
        f"redacted/{uuid4()}.{suffix}"
    )


async def _mark_redaction_failed(artifact_id: UUID, reason: str) -> None:
    """Record a redaction failure without clearing the PII review gate."""
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, artifact_id)
        if artifact is None:
            return
        metadata = dict(artifact.metadata_vector or {})
        redaction = dict(metadata.get("redaction") or {})
        redaction.update(
            {
                "status": "failed",
                "failure_reason": reason[:500],
                "failed_at": datetime.now(UTC).isoformat(),
            }
        )
        metadata["redaction"] = redaction
        artifact.metadata_vector = metadata
        artifact.pii_review_needed = True
        artifact.processing_status = "flagged_pii"
        await write_audit(
            db=db,
            actor_id=None,
            action="artifact_redaction_failed",
            target_type="artifact",
            target_id=artifact.id,
            metadata={
                "framework_id": str(artifact.framework_id),
                "reason": reason[:500],
            },
        )
        await db.commit()


async def _redact_artifact_impl(artifact_id: str) -> dict[str, Any]:
    """Generate and store a redacted review copy for one PII-flagged Artifact."""
    parsed_artifact_id = UUID(artifact_id)
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}
        if not artifact.pii_review_needed:
            return {"artifact_id": artifact_id, "status": "skipped"}
        metadata = artifact.metadata_vector or {}
        extraction = metadata.get("extraction", {})
        text = str(extraction.get("text", ""))
        file_key = artifact.file_key
        mime_type = artifact.mime_type

    findings, values = _pii_values(text)
    if not values:
        await _mark_redaction_failed(parsed_artifact_id, "No PII values detected.")
        return {"artifact_id": artifact_id, "status": "failed"}

    settings = get_settings()
    try:
        with tempfile.NamedTemporaryFile() as source_file:
            s3.storage.download_file(
                settings.s3_artifacts_bucket,
                file_key,
                source_file.name,
            )
            # Read the path fresh rather than the pre-opened handle: boto3's
            # download_file atomically replaces the destination inode, so the
            # original NamedTemporaryFile handle would read an empty file.
            with open(source_file.name, "rb") as downloaded:
                source_bytes = downloaded.read()
        redacted_bytes = redact_file_bytes(source_bytes, mime_type, values)
        with tempfile.NamedTemporaryFile() as redacted_file:
            redacted_file.write(redacted_bytes)
            redacted_file.flush()
            scan_status = scan_file_for_virus(redacted_file.name)
        if scan_status != "clean":
            raise RedactionError("Generated redacted artifact failed virus scan.")
    except Exception as exc:
        await _mark_redaction_failed(parsed_artifact_id, str(exc))
        return {"artifact_id": artifact_id, "status": "failed"}

    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}
        clean_file_key = _redacted_key(artifact)
        s3.storage.upload_bytes(
            settings.s3_artifacts_bucket,
            clean_file_key,
            redacted_bytes,
            artifact.mime_type,
        )
        artifact.clean_file_key = clean_file_key
        artifact.pii_review_needed = True
        artifact.processing_status = "flagged_pii"
        metadata = dict(artifact.metadata_vector or {})
        metadata["redaction"] = {
            "status": "generated",
            "clean_file_key": clean_file_key,
            "pii_types_found": sorted({finding.entity_type for finding in findings}),
            "generated_at": datetime.now(UTC).isoformat(),
        }
        artifact.metadata_vector = metadata
        audit = await db.scalar(
            select(ArtifactPiiAudit).where(
                ArtifactPiiAudit.artifact_id == parsed_artifact_id
            )
        )
        if audit is None:
            audit = ArtifactPiiAudit(artifact_id=parsed_artifact_id)
            db.add(audit)
        audit.pii_types_found = sorted({finding.entity_type for finding in findings})
        audit.auto_redacted = True
        audit.flagged_for_review = True
        await write_audit(
            db=db,
            actor_id=None,
            action="artifact_redaction_generated",
            target_type="artifact",
            target_id=artifact.id,
            metadata={
                "framework_id": str(artifact.framework_id),
                "pii_types_found": audit.pii_types_found,
            },
        )
        await db.commit()

    return {
        "artifact_id": artifact_id,
        "status": "redacted",
        "clean_file_key": clean_file_key,
    }


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def redact_artifact(self: Any, artifact_id: str) -> dict[str, Any]:
    """Celery wrapper for format-preserving Artifact redaction."""
    log = logger.bind(
        module="artifacts",
        action="redact_artifact",
        task_id=self.request.id,
        artifact_id=artifact_id,
    )
    log.info("task_started")
    try:
        result = run_async(_redact_artifact_impl(artifact_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
