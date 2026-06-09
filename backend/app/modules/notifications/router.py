"""Notifications API router."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.notifications import service
from app.modules.notifications.schemas import (
    MarkAllReadResponse,
    NotificationItem,
    NotificationsResponse,
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("", response_model=NotificationsResponse)
async def list_notifications(
    current_user: CurrentUser,
    db: DatabaseSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    unread_only: bool = Query(default=False),
) -> NotificationsResponse:
    """List notifications owned by the authenticated user."""
    return await service.list_notifications(
        db=db,
        user=current_user,
        page=page,
        page_size=page_size,
        unread_only=unread_only,
    )


@router.post("/read-all", response_model=MarkAllReadResponse)
async def mark_all_notifications_read(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> MarkAllReadResponse:
    """Mark every unread notification owned by the current user as read."""
    updated_count = await service.mark_all_notifications_read(
        db=db,
        user=current_user,
    )
    return MarkAllReadResponse(updated_count=updated_count)


@router.patch("/{notification_id}/read", response_model=NotificationItem)
async def mark_notification_read(
    notification_id: UUID,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> NotificationItem:
    """Mark a single owned notification as read."""
    return await service.mark_notification_read(
        db=db,
        user=current_user,
        notification_id=notification_id,
    )
