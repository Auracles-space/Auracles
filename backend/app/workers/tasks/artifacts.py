"""Artifact processing Celery tasks.

This module owns the virus-scan entrypoint and the top-level processing
entrypoint dispatched after a clean scan.
"""

from __future__ import annotations

import tempfile
from typing import Any
from uuid import UUID

from loguru import logger

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.frameworks.models_artifact import Artifact
from app.workers.async_runner import run_async
from app.workers.celery_app import app
from app.workers.tasks.processing.orchestrator import _process_artifact_impl


@app.task(bind=True)  # type: ignore[untyped-decorator]
def process_artifact(self: Any, artifact_id: str) -> None:
    """Run Artifact processing steps after the virus scan is clean."""
    log = logger.bind(
        module="artifacts",
        action="process_artifact",
        task_id=self.request.id,
        artifact_id=artifact_id,
    )
    log.info("task_started")
    result = run_async(_process_artifact_impl(artifact_id))
    log.info("task_completed", result=result)


def scan_file_with_clamav(path: str) -> str:
    """Return `clean` or `infected` after scanning a local file with ClamAV."""
    import clamd  # type: ignore[import-untyped]

    result = clamd.ClamdUnixSocket().scan(path)
    if result is None:
        return "clean"
    status = next(iter(result.values()))[0]
    return "infected" if status == "FOUND" else "clean"


async def _set_scan_result(
    artifact_id: UUID,
    scan_status: str,
    processing_status: str,
    audit_action: str,
) -> None:
    """Persist a scan state transition and audit record."""
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, artifact_id)
        if artifact is None:
            return
        artifact.scan_status = scan_status
        artifact.processing_status = processing_status
        await write_audit(
            db=db,
            actor_id=None,
            action=audit_action,
            target_type="artifact",
            target_id=artifact.id,
            metadata={
                "framework_id": str(artifact.framework_id),
                "scan_status": scan_status,
                "processing_status": processing_status,
            },
        )
        await db.commit()


async def _scan_artifact_impl(
    artifact_id: str,
    scan_file: Any | None = None,
    process_task: Any | None = None,
) -> str:
    """Download, scan, persist status, and dispatch processing when clean."""
    resolved_scan_file = scan_file or scan_file_with_clamav
    resolved_process_task = process_task or process_artifact
    parsed_artifact_id = UUID(artifact_id)
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return "missing"
        file_key = artifact.file_key

    settings = get_settings()
    with tempfile.NamedTemporaryFile() as local_file:
        s3.storage.download_file(
            settings.s3_artifacts_bucket,
            file_key,
            local_file.name,
        )
        scan_status = resolved_scan_file(local_file.name)

    if scan_status == "infected":
        await _set_scan_result(
            parsed_artifact_id,
            scan_status="infected",
            processing_status="failed",
            audit_action="virus_detected",
        )
        return "infected"

    await _set_scan_result(
        parsed_artifact_id,
        scan_status="clean",
        processing_status="processing",
        audit_action="artifact_scan_complete",
    )
    resolved_process_task.delay(artifact_id)
    return "clean"


@app.task(bind=True, max_retries=5)  # type: ignore[untyped-decorator]
def scan_artifact(self: Any, artifact_id: str) -> None:
    """Scan an uploaded Artifact for malware before further processing."""
    log = logger.bind(
        module="artifacts",
        action="scan_artifact",
        task_id=self.request.id,
        artifact_id=artifact_id,
    )
    log.info("task_started")
    try:
        result = run_async(_scan_artifact_impl(artifact_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        if self.request.retries >= self.max_retries:
            run_async(
                _set_scan_result(
                    UUID(artifact_id),
                    scan_status="error",
                    processing_status="failed",
                    audit_action="artifact_processing_failed",
                )
            )
            return
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
