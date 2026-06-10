"""Pydantic schemas for public Explore marketplace responses."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ExploreSort = Literal[
    "newest",
    "top-rated",
    "most-purchased",
    "price_asc",
    "price_desc",
]
ExploreAttestationStatus = Literal["pending_acceptance", "attested", "none"]


class ExploreAttestationBadge(BaseModel):
    """Public trust badge for a Framework-target Attestation."""

    id: UUID
    status: Literal["pending_acceptance", "attested"]
    outcome: Literal["approved", "conditional", "rejected"]
    report_key: str
    issued_at: datetime | None


class ExploreFrameworkCard(BaseModel):
    """Public catalog card for one published Framework."""

    id: UUID
    title: str
    description: str
    version: str
    category: str
    sector: str | None
    industry: str | None
    function: str | None
    tags: list[str]
    jurisdiction: str | None
    complexity: int | None
    org_size: str | None
    lifecycle_stage: str | None
    price: Decimal
    currency: str
    license_types: list[str]
    thumbnail_key: str | None
    rarity_score: Decimal | None
    attestation_badge: ExploreAttestationBadge | None = None
    owned: bool = False
    published_at: datetime | None


class ExploreFrameworkListResponse(BaseModel):
    """Paginated public catalog response."""

    items: list[ExploreFrameworkCard]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    sort: ExploreSort
    sort_shim: bool = False


class ExploreArtifactSummary(BaseModel):
    """Public Artifact metadata shown on Framework detail pages."""

    id: UUID
    name: str
    file_size: int
    mime_type: str
    created_at: datetime


class ExploreFrameworkDetail(ExploreFrameworkCard):
    """Public Framework detail payload."""

    preview_artifact_id: UUID | None
    preview_url: str | None
    artifacts: list[ExploreArtifactSummary]
