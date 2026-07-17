"""Pydantic schemas for public Explore marketplace responses."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.attestation.schemas import PublicCredentialResponse
from app.modules.reputation.schemas import ReputationSummary

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
    # Null while pending_acceptance: a submitted-but-unaccepted report must not
    # publicize its outcome. Set once the attestation is accepted (closed).
    outcome: Literal["approved", "conditional", "rejected"] | None = None
    report_key: str
    issued_at: datetime | None
    attestation_count: int = 1


class AttestationBadgeDetail(BaseModel):
    """Full version-locked attestation badge for the framework page.

    Presents attestor-org identity for org-attested badges (``attestor_org_id`` /
    ``attestor_org_slug`` set, ``attestor_id`` null) and legacy individual
    identity for pre-org badges (``attestor_id`` set, org fields null). Never
    exposes the reviewing member who performed an org attestation.
    """

    id: UUID
    review_type: str
    outcome: Literal["approved", "conditional", "rejected"]
    attestor_id: UUID | None = None
    attestor_org_id: UUID | None = None
    attestor_org_slug: str | None = None
    attestor_display_name: str
    verification_level: int | None = None
    credentials: list[PublicCredentialResponse] = Field(default_factory=list)
    issued_at: datetime
    framework_version: str | None
    newer_version_exists: bool


class ExploreFrameworkCard(BaseModel):
    """Public catalog card for one published Framework."""

    id: UUID
    contributor_id: UUID | None
    contributor_org_id: UUID | None = None
    contributor_name: str
    contributor_slug: str | None = None
    contributor_verification_level: int | None = None
    contributor_reputation_score: Decimal | None = Field(
        default=None,
        decimal_places=2,
    )
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
    reputation: ReputationSummary | None = None
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

    org_price: Decimal | None = None
    preview_artifact_id: UUID | None
    preview_url: str | None
    artifacts: list[ExploreArtifactSummary]
    attestation_badges: list[AttestationBadgeDetail] = Field(default_factory=list)


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
    reputation: ReputationSummary | None = None
    is_deactivated: bool = False
    published_framework_count: int
    published_frameworks: list[ExploreFrameworkCard]
    verified_credentials: list[PublicCredentialResponse] = []


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
