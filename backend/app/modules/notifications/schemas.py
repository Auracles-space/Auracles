"""Pydantic schemas for notification delivery and preference endpoints.

This module covers both the end-user bell surfaces and the settings preference
matrix used to gate product notification delivery by channel.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class NotificationPreferenceChannelItem(BaseModel):
    """One channel toggle for a single notification event type."""

    channel: str
    enabled: bool
    locked: bool


class NotificationPreferenceItem(BaseModel):
    """One notification event type grouped under a settings category."""

    notification_type: str
    label: str
    description: str
    channels: list[NotificationPreferenceChannelItem]


class NotificationPreferenceCategory(BaseModel):
    """One settings category grouping multiple notification event types."""

    category: str
    label: str
    preferences: list[NotificationPreferenceItem]


class NotificationPreferencesResponse(BaseModel):
    """Effective notification preference matrix for the current user."""

    categories: list[NotificationPreferenceCategory]


class NotificationPreferenceUpdateItem(BaseModel):
    """One per-event per-channel preference change requested by the owner."""

    notification_type: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    enabled: bool


class NotificationPreferencesUpdateRequest(BaseModel):
    """PATCH body for notification preference updates."""

    updates: list[NotificationPreferenceUpdateItem] = Field(min_length=1)
