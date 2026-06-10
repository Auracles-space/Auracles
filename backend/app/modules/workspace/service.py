"""Workspace message persistence and upload-session validation."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.auth.models import User
from app.modules.projects.models import Project, Proposal
from app.modules.realtime.pubsub import publish_to_channel
from app.modules.workspace.models import WorkspaceMessage, WorkspaceUploadSession
from app.modules.workspace.schemas import (
    WorkspaceMessageCreateRequest,
    WorkspaceMessagesResponse,
    WorkspaceUploadCreateRequest,
    WorkspaceUploadSessionResponse,
)
from app.workers.tasks.workspace_scan import scan_workspace_upload

WORKSPACE_UPLOAD_TTL_SECONDS = 300
WORKSPACE_UPLOAD_MAX_BYTES = 25 * 1024 * 1024


def _safe_file_name(file_name: str) -> str:
    """Return a path-safe file name segment for workspace S3 keys."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", file_name.strip()).strip("-")
    return cleaned or "upload"


async def is_project_member(
    db: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
) -> bool:
    """Return whether a user is the Operator or accepted Contributor."""
    project = await db.scalar(select(Project).where(Project.id == project_id))
    if project is None:
        return False
    if project.operator_id == user_id:
        return True
    if project.accepted_proposal_id is None:
        return False
    contributor_id = await db.scalar(
        select(Proposal.contributor_id).where(
            Proposal.id == project.accepted_proposal_id,
            Proposal.project_id == project.id,
            Proposal.status == "accepted",
        )
    )
    return contributor_id == user_id


async def _require_project_member(
    db: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
) -> Project:
    """Load a Project and raise unless the user belongs to its workspace."""
    project = await db.scalar(select(Project).where(Project.id == project_id))
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    if not await is_project_member(db, project_id=project.id, user_id=user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Project members can access workspace messages.",
        )
    return project


async def _publish_workspace_event(
    project_id: UUID,
    *,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Publish a workspace event without failing the committed request path."""
    try:
        await publish_to_channel(
            f"project:{project_id}",
            event_type,
            payload,
        )
    except Exception as exc:
        logger.bind(
            module="workspace",
            action="publish_workspace_event",
            project_id=project_id,
        ).warning("workspace_publish_failed", error=str(exc))


def _message_query(project_id: UUID) -> Select[tuple[WorkspaceMessage]]:
    """Return the base query for workspace message list endpoints."""
    return select(WorkspaceMessage).where(WorkspaceMessage.project_id == project_id)


async def create_upload_session(
    *,
    db: AsyncSession,
    user: User,
    project_id: UUID,
    payload: WorkspaceUploadCreateRequest,
) -> WorkspaceUploadSessionResponse:
    """Create a presigned POST upload session for a Project member."""
    user_id = user.id
    if payload.size_bytes > WORKSPACE_UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Workspace upload is too large.",
        )
    if db.in_transaction():
        await db.rollback()

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=WORKSPACE_UPLOAD_TTL_SECONDS)
    key = (
        f"workspace/{project_id}/{user_id}/{uuid4()}-"
        f"{_safe_file_name(payload.file_name)}"
    )
    async with db.begin():
        await _require_project_member(db, project_id=project_id, user_id=user_id)
        session = WorkspaceUploadSession(
            project_id=project_id,
            user_id=user_id,
            s3_key=key,
            content_type=payload.content_type,
            size_limit=WORKSPACE_UPLOAD_MAX_BYTES,
            expires_at=expires_at,
        )
        db.add(session)
        await db.flush()
        await db.refresh(session)

    settings = get_settings()
    post = s3.storage.presigned_post(
        settings.s3_artifacts_bucket,
        key,
        payload.content_type,
        WORKSPACE_UPLOAD_MAX_BYTES,
        WORKSPACE_UPLOAD_TTL_SECONDS,
    )
    return WorkspaceUploadSessionResponse(
        id=session.id,
        s3_key=key,
        url=str(post["url"]),
        fields={str(key_): str(value) for key_, value in post["fields"].items()},
        expires_at=expires_at,
        size_limit=WORKSPACE_UPLOAD_MAX_BYTES,
    )


async def _consume_upload_sessions(
    *,
    db: AsyncSession,
    project_id: UUID,
    user_id: UUID,
    file_keys: list[str],
    now: datetime,
) -> None:
    """Validate and consume upload sessions for message attachments."""
    rows = (
        (
            await db.execute(
                select(WorkspaceUploadSession)
                .where(
                    WorkspaceUploadSession.project_id == project_id,
                    WorkspaceUploadSession.user_id == user_id,
                    WorkspaceUploadSession.s3_key.in_(file_keys),
                    WorkspaceUploadSession.consumed_at.is_(None),
                    WorkspaceUploadSession.expires_at > now,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    by_key = {row.s3_key: row for row in rows}
    if set(by_key) != set(file_keys):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Message contains invalid or expired workspace upload keys.",
        )
    for row in rows:
        row.consumed_at = now


async def create_message(
    *,
    db: AsyncSession,
    user: User,
    project_id: UUID,
    payload: WorkspaceMessageCreateRequest,
) -> WorkspaceMessage:
    """Persist a user workspace message and queue attachment scanning."""
    user_id = user.id
    body = payload.body.strip() if payload.body is not None else None
    file_keys = payload.file_keys
    if body is None and file_keys is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Message requires body text or file attachments.",
        )
    if db.in_transaction():
        await db.rollback()

    now = datetime.now(UTC)
    async with db.begin():
        await _require_project_member(db, project_id=project_id, user_id=user_id)
        if file_keys is not None:
            await _consume_upload_sessions(
                db=db,
                project_id=project_id,
                user_id=user_id,
                file_keys=file_keys,
                now=now,
            )
        message = WorkspaceMessage(
            project_id=project_id,
            sender_id=user_id,
            body=body,
            file_keys=file_keys,
            scan_status="pending_scan" if file_keys else "visible",
        )
        db.add(message)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=user_id,
            action="workspace_message_created",
            target_type="workspace_message",
            target_id=message.id,
            metadata={
                "project_id": str(project_id),
                "has_files": file_keys is not None,
            },
        )
        await db.flush()
        await db.refresh(message)

    if file_keys is not None:
        scan_workspace_upload.delay(str(message.id))
    else:
        await _publish_workspace_event(
            project_id,
            event_type="message_created",
            payload={"message_id": str(message.id)},
        )
    return message


async def list_messages(
    *,
    db: AsyncSession,
    user: User,
    project_id: UUID,
    before: datetime | None,
    limit: int,
) -> WorkspaceMessagesResponse:
    """List visible workspace messages for a Project member."""
    await _require_project_member(db, project_id=project_id, user_id=user.id)
    query = _message_query(project_id).where(
        or_(
            WorkspaceMessage.scan_status == "visible",
            WorkspaceMessage.sender_id == user.id,
            WorkspaceMessage.system_event.is_not(None),
        ),
        WorkspaceMessage.scan_status != "quarantined",
    )
    if before is not None:
        query = query.where(WorkspaceMessage.created_at < before)
    rows = await db.execute(
        query.order_by(WorkspaceMessage.created_at.desc()).limit(limit)
    )
    messages = list(reversed(rows.scalars().all()))
    return WorkspaceMessagesResponse(messages=messages)
