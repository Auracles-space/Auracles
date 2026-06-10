"""Workspace REST API routes."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.workspace import service
from app.modules.workspace.schemas import (
    WorkspaceMessageCreateRequest,
    WorkspaceMessageResponse,
    WorkspaceMessagesResponse,
    WorkspaceUploadCreateRequest,
    WorkspaceUploadSessionResponse,
)

router = APIRouter(prefix="/projects", tags=["Workspace"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
BeforeQuery = Annotated[datetime | None, Query()]
LimitQuery = Annotated[int, Query(ge=1, le=100)]


@router.post(
    "/{project_id}/messages/uploads",
    response_model=WorkspaceUploadSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_upload_session(
    project_id: UUID,
    payload: WorkspaceUploadCreateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> WorkspaceUploadSessionResponse:
    """Create a presigned POST upload session for a Project member."""
    return await service.create_upload_session(
        db=db,
        user=current_user,
        project_id=project_id,
        payload=payload,
    )


@router.post(
    "/{project_id}/messages",
    response_model=WorkspaceMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_message(
    project_id: UUID,
    payload: WorkspaceMessageCreateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> WorkspaceMessageResponse:
    """Create a user workspace message."""
    message = await service.create_message(
        db=db,
        user=current_user,
        project_id=project_id,
        payload=payload,
    )
    return WorkspaceMessageResponse.model_validate(message)


@router.get("/{project_id}/messages", response_model=WorkspaceMessagesResponse)
async def list_workspace_messages(
    project_id: UUID,
    current_user: CurrentUser,
    db: DatabaseSession,
    before: BeforeQuery = None,
    limit: LimitQuery = 50,
) -> WorkspaceMessagesResponse:
    """List visible workspace messages for a Project member."""
    return await service.list_messages(
        db=db,
        user=current_user,
        project_id=project_id,
        before=before,
        limit=limit,
    )
