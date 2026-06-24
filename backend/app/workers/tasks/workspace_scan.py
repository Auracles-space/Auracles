"""Workspace attachment virus scanning tasks."""

from __future__ import annotations

import tempfile
from typing import Any
from uuid import UUID

from loguru import logger

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.projects import notifications as project_notifications
from app.modules.realtime.pubsub import publish_to_channel
from app.modules.workspace.models import WorkspaceMessage
from app.workers.async_runner import run_async
from app.workers.celery_app import app
from app.workers.tasks.artifacts import scan_file_with_clamav


async def _publish_message_visible(message: WorkspaceMessage) -> None:
    """Publish a realtime event for a newly visible workspace message."""
    await publish_to_channel(
        f"project:{message.project_id}",
        "message_visible",
        {"message_id": str(message.id)},
    )


async def _set_workspace_scan_result(
    *,
    message_id: UUID,
    scan_status: str,
    audit_action: str,
) -> str:
    """Persist a workspace scan state transition and audit record."""
    async with async_session_factory() as db:
        async with db.begin():
            message = await db.get(WorkspaceMessage, message_id)
            if message is None:
                return "missing"
            message.scan_status = scan_status
            await write_audit(
                db=db,
                actor_id=message.sender_id,
                action=audit_action,
                target_type="workspace_message",
                target_id=message.id,
                metadata={
                    "project_id": str(message.project_id),
                    "scan_status": scan_status,
                },
            )
            quarantine_uploader_id = message.sender_id
            quarantine_project_id = message.project_id
            quarantine_message_id = message.id
        if scan_status == "visible":
            await _publish_message_visible(message)
        elif scan_status == "quarantined" and quarantine_uploader_id is not None:
            # Tell the uploader their file was rejected; system messages have no
            # sender, so only notify when a real uploader is on the record.
            project_notifications.notify_workspace_file_quarantined(
                uploader_id=quarantine_uploader_id,
                project_id=quarantine_project_id,
                message_id=quarantine_message_id,
            )
    return scan_status


async def _scan_workspace_upload_impl(
    message_id: str,
    scan_file: Any | None = None,
) -> str:
    """Download and scan workspace attachments, then update visibility."""
    resolved_scan_file = scan_file or scan_file_with_clamav
    parsed_message_id = UUID(message_id)
    async with async_session_factory() as db:
        message = await db.get(WorkspaceMessage, parsed_message_id)
        if message is None:
            return "missing"
        if message.scan_status != "pending_scan":
            return message.scan_status
        file_keys = list(message.file_keys or [])

    settings = get_settings()
    for file_key in file_keys:
        with tempfile.NamedTemporaryFile() as local_file:
            s3.storage.download_file(
                settings.s3_artifacts_bucket,
                file_key,
                local_file.name,
            )
            if resolved_scan_file(local_file.name) == "infected":
                return await _set_workspace_scan_result(
                    message_id=parsed_message_id,
                    scan_status="quarantined",
                    audit_action="workspace_file_quarantined",
                )

    return await _set_workspace_scan_result(
        message_id=parsed_message_id,
        scan_status="visible",
        audit_action="workspace_file_scan_complete",
    )


@app.task(bind=True, max_retries=5)  # type: ignore[untyped-decorator]
def scan_workspace_upload(self: Any, message_id: str) -> str | None:
    """Scan workspace message attachments before publishing visibility."""
    log = logger.bind(
        module="workspace",
        action="scan_workspace_upload",
        task_id=self.request.id,
        message_id=message_id,
    )
    log.info("task_started")
    try:
        result = run_async(_scan_workspace_upload_impl(message_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        if self.request.retries >= self.max_retries:
            return run_async(
                _set_workspace_scan_result(
                    message_id=UUID(message_id),
                    scan_status="quarantined",
                    audit_action="workspace_file_quarantined",
                )
            )
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
