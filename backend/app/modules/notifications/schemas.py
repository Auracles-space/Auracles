"""Pydantic schemas for notification endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationItem(BaseModel):
    """Serializable notification row returned to the owning user."""

    id: UUID
    type: str
    title: str
    body: str
    link: str | None
    payload: dict[str, Any] | None
    read_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationsResponse(BaseModel):
    """Paginated notification list plus unread badge count."""

    notifications: list[NotificationItem]
    unread_count: int
    total: int
    page: int
    page_size: int


class MarkAllReadResponse(BaseModel):
    """Count of notifications changed by a read-all request."""

    updated_count: int
