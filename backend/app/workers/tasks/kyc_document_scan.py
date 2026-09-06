"""KYC document virus scanning task.

Mirrors the Deliverable and workspace attachment scans: a submitted identity
document is downloaded from private storage and run through ClamAV. The document
stays ``pending_scan`` until clean; an infected file flips it to ``quarantined``.

This matters more here than elsewhere in the product. Every other scanned upload
is opened by the user who asked for it; a KYC document is opened by an
administrator during review, so an unscanned path would let any registered
account put a chosen file in front of staff. Admin download is gated on
``clean``.

Maps to: FR-AUTH-009.
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
from app.modules.auth.models import KycDocument
from app.workers.async_runner import run_async
from app.workers.celery_app import app
from app.workers.tasks.artifacts import scan_file_with_clamav


async def _set_kyc_document_scan_result(
    *,
    document_id: UUID,
    scan_status: str,
    audit_action: str,
) -> str:
    """Persist a KYC document scan transition and audit record.

    Args:
        document_id: The document whose scan state is being recorded.
        scan_status: The terminal scan state to write.
        audit_action: Audit action name for the transition.

    Returns:
        The written scan status, or ``missing`` if the row is gone (the account
        may have been deleted between dispatch and execution).
    """
    async with async_session_factory() as db:
        async with db.begin():
            document = await db.get(KycDocument, document_id)
            if document is None:
                return "missing"
            document.scan_status = scan_status
            await write_audit(
                db=db,
                actor_id=document.user_id,
                action=audit_action,
                target_type="kyc_document",
                target_id=document.id,
                metadata={
                    "doc_type": document.doc_type,
                    "scan_status": scan_status,
                },
            )
    return scan_status


async def _scan_kyc_document_impl(
    document_id: str,
    scan_file: Any | None = None,
) -> str:
    """Download and scan one KYC document, then update its scan status.

    Args:
        document_id: The document id as a string (Celery argument).
        scan_file: Optional scanner override, for testing.

    Returns:
        The resulting scan status.
    """
    resolved_scan_file = scan_file or scan_file_with_clamav
    parsed_document_id = UUID(document_id)
    async with async_session_factory() as db:
        document = await db.get(KycDocument, parsed_document_id)
        if document is None:
            return "missing"
        # Idempotency: a re-delivered task must not re-scan a settled document.
        if document.scan_status != "pending_scan":
            return document.scan_status
        s3_key = document.s3_key

    settings = get_settings()
    with tempfile.NamedTemporaryFile() as local_file:
        s3.storage.download_file(
            settings.s3_artifacts_bucket,
            s3_key,
            local_file.name,
        )
        if resolved_scan_file(local_file.name) == "infected":
            return await _set_kyc_document_scan_result(
                document_id=parsed_document_id,
                scan_status="quarantined",
                audit_action="kyc_document_quarantined",
            )

    return await _set_kyc_document_scan_result(
        document_id=parsed_document_id,
        scan_status="clean",
        audit_action="kyc_document_scan_complete",
    )


@app.task(bind=True, max_retries=5)  # type: ignore[untyped-decorator]
def scan_kyc_document(self: Any, document_id: str) -> str | None:
    """Scan a submitted identity document before an admin may download it."""
    log = logger.bind(
        module="kyc",
        action="scan_kyc_document",
        task_id=self.request.id,
        document_id=document_id,
    )
    log.info("task_started")
    try:
        result = run_async(_scan_kyc_document_impl(document_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        if self.request.retries >= self.max_retries:
            # Exhausted retries quarantine rather than fail open: a document
            # that could not be proven clean must never reach a reviewer.
            return run_async(
                _set_kyc_document_scan_result(
                    document_id=UUID(document_id),
                    scan_status="quarantined",
                    audit_action="kyc_document_quarantined",
                )
            )
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
