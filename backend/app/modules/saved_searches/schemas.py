"""Pydantic schemas for Operator saved-search CRUD.

Request bodies validate names and Explore filter blobs before service code
persists them, keeping later alert matching tied to the live catalog contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.explore.schemas import ExploreSearchFilters


class SavedSearchCreateRequest(BaseModel):
    """Operator request body for creating a saved Explore search."""

    name: str = Field(min_length=1, max_length=100)
    filters: ExploreSearchFilters = Field(default_factory=ExploreSearchFilters)
    alert_enabled: bool = False


class SavedSearchUpdateRequest(BaseModel):
    """Operator request body for editing an owned saved search."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    filters: ExploreSearchFilters | None = None
    alert_enabled: bool | None = None


class SavedSearchResponse(BaseModel):
    """Operator-facing saved-search response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    filters: dict[str, Any]
    filter_version: int
    alert_enabled: bool
    last_alerted_at: datetime | None
    last_alerted_framework_id: UUID | None
    created_at: datetime
    updated_at: datetime


class SavedSearchListResponse(BaseModel):
    """List response for Operator-owned saved searches."""

    saved_searches: list[SavedSearchResponse]
