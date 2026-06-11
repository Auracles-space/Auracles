"""Pydantic schemas for Operator library and licensed downloads."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class LibraryItem(BaseModel):
    """One Framework license shown in an Operator's library."""

    license_id: UUID
    framework_id: UUID
    title: str
    version_at_grant: str
    current_version: str
    license_type: str
    source: str
    collection_id: UUID | None
    status: str
    seats_used: int
    seats_total: int | None
    price: Decimal
    currency: str
    thumbnail_key: str | None
    granted_at: datetime
    expires_at: datetime | None


class LibraryResponse(BaseModel):
    """Paginated Operator library response."""

    items: list[LibraryItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class ArtifactDownloadResponse(BaseModel):
    """Response containing a short-lived licensed Artifact download URL."""

    artifact_id: UUID
    framework_id: UUID
    license_id: UUID
    download_url: str
    expires_in: int
