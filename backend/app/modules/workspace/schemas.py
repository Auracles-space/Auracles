"""Pydantic schemas for Project workspace endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceUploadCreateRequest(BaseModel):
    """Request body for creating a workspace presigned upload session."""

    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0, le=25 * 1024 * 1024)


class WorkspaceUploadSessionResponse(BaseModel):
    """Presigned POST response for a single workspace file upload."""

    id: UUID
    s3_key: str
    url: str
    fields: dict[str, str]
    expires_at: datetime
    size_limit: int


class WorkspaceMessageCreateRequest(BaseModel):
    """Request body for posting a user workspace message."""

    body: str | None = Field(default=None, min_length=1, max_length=10000)
    file_keys: list[str] | None = Field(default=None, min_length=1, max_length=20)


class WorkspaceMessageResponse(BaseModel):
    """Workspace message response returned to Project members."""

    id: UUID
    project_id: UUID
    sender_id: UUID | None
    body: str | None
    file_keys: list[str] | None
    scan_status: str
    system_event: str | None
    system_payload: dict[str, object] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkspaceMessagesResponse(BaseModel):
    """List response for Project workspace messages."""

    messages: list[WorkspaceMessageResponse]
