"""Celery tasks for scanning Attestation and Credential evidence uploads."""

from __future__ import annotations

import tempfile
from typing import Any
from uuid import UUID

from loguru import logger

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.attestation.models import AttestationUploadSession
from app.workers.async_runner import run_async
from app.workers.celery_app import app
from app.workers.tasks.artifacts import scan_file_with_clamav


async def _set_upload_scan_result(
    *,
    upload_session_id: UUID,
    scan_status: str,
    audit_action: str,
) -> str:
    """Persist an Attestation upload scan result and audit the transition."""
    async with async_session_factory() as db:
        async with db.begin():
            upload_session = await db.get(AttestationUploadSession, upload_session_id)
            if upload_session is None:
                return "missing"
            upload_session.scan_status = scan_status
            await write_audit(
                db=db,
                actor_id=upload_session.user_id,
                action=audit_action,
                target_type="attestation_upload_session",
                target_id=upload_session.id,
                metadata={
                    "purpose": upload_session.purpose,
                    "scan_status": scan_status,
                    "attestation_id": (
                        str(upload_session.attestation_id)
                        if upload_session.attestation_id is not None
                        else None
                    ),
                    "credential_id": (
                        str(upload_session.credential_id)
                        if upload_session.credential_id is not None
                        else None
                    ),
                },
            )
    return scan_status


async def _scan_attestation_upload_impl(
    upload_session_id: str,
    scan_file: Any | None = None,
) -> str:
    """Download and scan one evidence upload session from private S3."""
    resolved_scan_file = scan_file or scan_file_with_clamav
    parsed_upload_session_id = UUID(upload_session_id)
    async with async_session_factory() as db:
        upload_session = await db.get(
            AttestationUploadSession,
            parsed_upload_session_id,
        )
        if upload_session is None:
            return "missing"
        if upload_session.scan_status != "pending_scan":
            return upload_session.scan_status
        file_key = upload_session.s3_key

    settings = get_settings()
    with tempfile.NamedTemporaryFile() as local_file:
        s3.storage.download_file(
            settings.s3_artifacts_bucket,
            file_key,
            local_file.name,
        )
        scan_result = resolved_scan_file(local_file.name)

    if scan_result == "infected":
        return await _set_upload_scan_result(
            upload_session_id=parsed_upload_session_id,
            scan_status="infected",
            audit_action="attestation_upload_quarantined",
        )
    return await _set_upload_scan_result(
        upload_session_id=parsed_upload_session_id,
        scan_status="clean",
        audit_action="attestation_upload_scan_complete",
    )


@app.task(bind=True, max_retries=5)  # type: ignore[untyped-decorator]
def scan_attestation_upload(self: Any, upload_session_id: str) -> str | None:
    """Scan one Attestation upload session before it can be attached."""
    log = logger.bind(
        module="attestation",
        action="scan_attestation_upload",
        task_id=self.request.id,
        upload_session_id=upload_session_id,
    )
    log.info("task_started")
    try:
        result = run_async(_scan_attestation_upload_impl(upload_session_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        if self.request.retries >= self.max_retries:
            return run_async(
                _set_upload_scan_result(
                    upload_session_id=UUID(upload_session_id),
                    scan_status="error",
                    audit_action="attestation_upload_scan_failed",
                )
            )
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
