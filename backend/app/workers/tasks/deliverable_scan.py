"""Deliverable evidence virus scanning tasks.

Mirrors the workspace attachment scan: a Deliverable's uploaded files are
downloaded from S3 and run through ClamAV. The Deliverable stays ``pending_scan``
until clean (``visible``); an infected file flips it to ``quarantined``. Operator
approval is gated on ``visible`` so Escrow is never released for unscanned or
infected work.

Maps to: FR-PROJ-008.
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
from app.modules.projects.models import Deliverable
from app.workers.async_runner import run_async
from app.workers.celery_app import app
from app.workers.tasks.artifacts import scan_file_with_clamav


async def _set_deliverable_scan_result(
    *,
    deliverable_id: UUID,
    scan_status: str,
    audit_action: str,
) -> str:
    """Persist a Deliverable scan transition and audit record."""
    async with async_session_factory() as db:
        async with db.begin():
            deliverable = await db.get(Deliverable, deliverable_id)
            if deliverable is None:
                return "missing"
            deliverable.scan_status = scan_status
            await write_audit(
                db=db,
                actor_id=deliverable.contributor_id,
                action=audit_action,
                target_type="deliverable",
                target_id=deliverable.id,
                metadata={
                    "milestone_id": str(deliverable.milestone_id),
                    "scan_status": scan_status,
                },
            )
    return scan_status


async def _scan_deliverable_upload_impl(
    deliverable_id: str,
    scan_file: Any | None = None,
) -> str:
    """Download and scan a Deliverable's files, then update its scan status."""
    resolved_scan_file = scan_file or scan_file_with_clamav
    parsed_deliverable_id = UUID(deliverable_id)
    async with async_session_factory() as db:
        deliverable = await db.get(Deliverable, parsed_deliverable_id)
        if deliverable is None:
            return "missing"
        if deliverable.scan_status != "pending_scan":
            return deliverable.scan_status
        file_keys = list(deliverable.file_keys or [])

    settings = get_settings()
    for file_key in file_keys:
        with tempfile.NamedTemporaryFile() as local_file:
            s3.storage.download_file(
                settings.s3_artifacts_bucket,
                file_key,
                local_file.name,
            )
            if resolved_scan_file(local_file.name) == "infected":
                return await _set_deliverable_scan_result(
                    deliverable_id=parsed_deliverable_id,
                    scan_status="quarantined",
                    audit_action="deliverable_file_quarantined",
                )

    return await _set_deliverable_scan_result(
        deliverable_id=parsed_deliverable_id,
        scan_status="visible",
        audit_action="deliverable_file_scan_complete",
    )


@app.task(bind=True, max_retries=5)  # type: ignore[untyped-decorator]
def scan_deliverable_upload(self: Any, deliverable_id: str) -> str | None:
    """Scan a submitted Deliverable's files before Operator approval is allowed."""
    log = logger.bind(
        module="projects",
        action="scan_deliverable_upload",
        task_id=self.request.id,
        deliverable_id=deliverable_id,
    )
    log.info("task_started")
    try:
        result = run_async(_scan_deliverable_upload_impl(deliverable_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        if self.request.retries >= self.max_retries:
            return run_async(
                _set_deliverable_scan_result(
                    deliverable_id=UUID(deliverable_id),
                    scan_status="quarantined",
                    audit_action="deliverable_file_quarantined",
                )
            )
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
