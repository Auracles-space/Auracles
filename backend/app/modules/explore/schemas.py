"""Pydantic schemas for public Explore marketplace responses."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ExploreSort = Literal[
    "newest",
    "top-rated",
    "most-purchased",
    "price_asc",
    "price_desc",
]
ExploreAttestationStatus = Literal[
    "pending_acceptance",
    "attested",
    "conditionally_attested",
    "none",
]


class ExploreAttestationBadge(BaseModel):
    """Public trust badge for a Framework or Contributor-target Attestation."""

    id: UUID
    status: Literal["pending_acceptance", "attested", "conditionally_attested"]
    outcome: Literal["approved", "conditional", "rejected"]
    report_key: str
    issued_at: datetime | None
    attestation_count: int = 1


class ExploreFrameworkCard(BaseModel):
    """Public catalog card for one published Framework."""

    id: UUID
    contributor_id: UUID
    contributor_name: str
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
    average_review_score: Decimal | None = Field(default=None, decimal_places=2)
    review_count: int = 0
    attestation_badge: ExploreAttestationBadge | None = None
    owned: bool = False
    published_at: datetime | None


class ExploreFrameworkCatalogItem(ExploreFrameworkCard):
    """Framework card shape used inside the mixed Explore catalog."""

    item_type: Literal["framework"] = "framework"


class ExploreCollectionMemberSummary(BaseModel):
    """Public member Framework summary embedded in Collection cards."""

    framework_id: UUID
    title: str
    version: str
    category: str
    price: Decimal
    currency: str
    thumbnail_key: str | None


class ExploreCollectionCard(BaseModel):
    """Public catalog card for one published Collection."""

    item_type: Literal["collection"] = "collection"
    id: UUID
    contributor_id: UUID
    contributor_name: str
    title: str
    description: str
    bundle_price: Decimal
    currency: str
    member_price_sum: Decimal
    savings_amount: Decimal
    savings_percent: Decimal = Field(decimal_places=2)
    member_count: int
    members: list[ExploreCollectionMemberSummary]
    created_at: datetime
    updated_at: datetime


class ExploreCollectionListResponse(BaseModel):
    """Paginated public Collection catalog response."""

    items: list[ExploreCollectionCard]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    sort: ExploreSort
    sort_shim: bool = False


class ExploreCollectionDetail(ExploreCollectionCard):
    """Public Collection detail payload."""

    already_owned_member_ids: list[UUID] = Field(default_factory=list)


ExploreCatalogItem = Annotated[
    ExploreFrameworkCatalogItem | ExploreCollectionCard,
    Field(discriminator="item_type"),
]


class ExploreCatalogResponse(BaseModel):
    """Paginated mixed catalog response for Framework and Collection cards."""

    items: list[ExploreCatalogItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    sort: ExploreSort
    sort_shim: bool = False


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


class ExploreContributorProfile(BaseModel):
    """Public Contributor profile for Explore discovery."""

    id: UUID
    display_name: str
    avatar_url: str | None
    bio: str | None
    location: str | None
    website: str | None
    attestation_badge: ExploreAttestationBadge | None = None
    attestation_count: int = 0
    is_deactivated: bool = False
    published_framework_count: int
    published_frameworks: list[ExploreFrameworkCard]


class ExploreSearchFilters(BaseModel):
    """Validated Explore filter blob persisted by saved searches.

    Pagination is intentionally excluded so a saved search captures query intent,
    not one temporary result page.
    """

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, min_length=1)
    category: str | None = None
    sector: str | None = None
    industry: str | None = None
    function: str | None = None
    jurisdiction: str | None = None
    complexity: int | None = Field(default=None, ge=1, le=5)
    org_size: str | None = None
    lifecycle_stage: str | None = None
    license_type: str | None = None
    price_min: Decimal | None = Field(default=None, ge=0)
    price_max: Decimal | None = Field(default=None, ge=0)
    attestation_status: ExploreAttestationStatus | None = None
    sort: ExploreSort = "newest"
