"""Pydantic schemas for contributor Framework CRUD.

Slice 2 keeps the API contributor-scoped and draft-focused. Public Explore
schemas arrive later when `/v1/explore` starts exposing published Frameworks.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.frameworks.taxonomy import (
    FrameworkCategory,
    FrameworkFunction,
    FrameworkIndustry,
    FrameworkSector,
)

FrameworkStatus = Literal[
    "draft",
    "submitted",
    "processing",
    "pipeline_passed",
    "pipeline_failed",
    "published",
    "unpublished",
    "suspended",
]
LicenseType = Literal["single_user", "team", "organizational", "enterprise"]
ChangeType = Literal["fix", "improvement", "major"]
OrgSize = Literal["startup", "small_business", "sme", "mid_market", "enterprise"]
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class PricingConfig(BaseModel):
    """Framework pricing and licensing options configured by a Contributor."""

    price: Decimal = Field(gt=0, decimal_places=2, max_digits=12)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    license_types: list[LicenseType] = Field(min_length=1)
    org_price: Decimal | None = Field(
        default=None,
        gt=0,
        decimal_places=2,
        max_digits=12,
    )
    commercial_rights: str | None = None
    usage_restrictions: str | None = None

    @field_validator("currency")
    @classmethod
    def currency_is_uppercase_iso_code(cls, value: str) -> str:
        """Normalize ISO-like currency codes to uppercase three-letter text."""
        currency = value.upper()
        if currency != "USD":
            raise ValueError("Only USD Framework pricing is supported.")
        return currency

    @model_validator(mode="after")
    def validate_org_pricing(self) -> "PricingConfig":
        """Enforce mandatory base tier and orphan org-price rejection rules."""
        if "single_user" not in self.license_types:
            raise ValueError("The single_user license tier is required.")
        if self.org_price is not None and "organizational" not in self.license_types:
            raise ValueError(
                "org_price requires the organizational license tier to be offered."
            )
        return self


class FrameworkCreate(BaseModel):
    """Request body for creating a draft Framework."""

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    source_project_id: UUID | None = None
    category: FrameworkCategory
    sector: FrameworkSector | None = None
    industry: FrameworkIndustry | None = None
    function: FrameworkFunction | None = None
    tags: list[str] = Field(default_factory=list)
    jurisdiction: str | None = Field(default=None, max_length=100)
    complexity: int | None = Field(default=None, ge=1, le=5)
    org_size: OrgSize | None = None
    lifecycle_stage: str | None = Field(default=None, max_length=100)
    pricing: PricingConfig

    @field_validator("tags")
    @classmethod
    def tags_are_trimmed(cls, value: list[str]) -> list[str]:
        """Trim tag text and remove accidental blank tags."""
        return [tag.strip() for tag in value if tag.strip()]


class FrameworkUpdate(BaseModel):
    """Request body for editing an owned draft Framework."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    category: FrameworkCategory | None = None
    sector: FrameworkSector | None = None
    industry: FrameworkIndustry | None = None
    function: FrameworkFunction | None = None
    tags: list[str] | None = None
    jurisdiction: str | None = Field(default=None, max_length=100)
    complexity: int | None = Field(default=None, ge=1, le=5)
    org_size: OrgSize | None = None
    lifecycle_stage: str | None = Field(default=None, max_length=100)
    pricing: PricingConfig | None = None

    @field_validator("tags")
    @classmethod
    def tags_are_trimmed(cls, value: list[str] | None) -> list[str] | None:
        """Trim tag text and remove accidental blank tags."""
        if value is None:
            return None
        return [tag.strip() for tag in value if tag.strip()]


class FrameworkMetadataUpdate(BaseModel):
    """Request body for editing Framework metadata without pricing changes."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    category: FrameworkCategory | None = None
    sector: FrameworkSector | None = None
    industry: FrameworkIndustry | None = None
    function: FrameworkFunction | None = None
    tags: list[str] | None = None
    jurisdiction: str | None = Field(default=None, max_length=100)
    complexity: int | None = Field(default=None, ge=1, le=5)
    org_size: OrgSize | None = None
    lifecycle_stage: str | None = Field(default=None, max_length=100)

    @field_validator("tags")
    @classmethod
    def tags_are_trimmed(cls, value: list[str] | None) -> list[str] | None:
        """Trim tag text and remove accidental blank tags."""
        if value is None:
            return None
        return [tag.strip() for tag in value if tag.strip()]


class FrameworkPricingUpdate(BaseModel):
    """Request body for editing Framework pricing and licensing fields."""

    pricing: PricingConfig


class FrameworkResponse(BaseModel):
    """Contributor-facing Framework representation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contributor_id: UUID | None
    contributor_org_id: UUID | None = None
    source_project_id: UUID | None
    title: str
    description: str
    version: str
    status: FrameworkStatus
    category: str
    sector: str | None
    industry: str | None
    function: str | None
    tags: list[str]
    jurisdiction: str | None
    complexity: int | None
    org_size: str | None
    lifecycle_stage: str | None
    pricing: PricingConfig
    preview_artifact_id: UUID | None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None

    @field_validator("version")
    @classmethod
    def version_is_semver(cls, value: str) -> str:
        """Validate persisted versions before returning them to clients."""
        if not SEMVER_PATTERN.fullmatch(value):
            raise ValueError("Framework version must use semantic version format.")
        return value


class FrameworkListItem(BaseModel):
    """Compact Framework row for the Contributor's dashboard list."""

    id: UUID
    title: str
    version: str
    status: FrameworkStatus
    category: str
    price: Decimal
    currency: str
    created_at: datetime
    updated_at: datetime

    @field_validator("version")
    @classmethod
    def version_is_semver(cls, value: str) -> str:
        """Validate persisted versions before returning them to clients."""
        if not SEMVER_PATTERN.fullmatch(value):
            raise ValueError("Framework version must use semantic version format.")
        return value


class ArtifactUploadUrlRequest(BaseModel):
    """Request body for creating a constrained Artifact upload target."""

    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=150)
    file_size: int = Field(gt=0)


class ArtifactUploadUrlResponse(BaseModel):
    """Response body for an S3 presigned POST Artifact upload target."""

    artifact_id: UUID
    upload_url: str
    fields: dict[str, str]
    file_key: str
    max_size: int
    expires_in: int


class ArtifactConfirmRequest(BaseModel):
    """Request body for confirming a browser-uploaded Artifact object."""

    artifact_id: UUID


class PreviewArtifactRequest(BaseModel):
    """Request body for selecting a Framework preview Artifact."""

    artifact_id: UUID


class SimilarityNoticeAcknowledgementRequest(BaseModel):
    """Request body for acknowledging a non-blocking similarity notice."""

    differentiation_note: str = Field(min_length=5, max_length=1000)

    @field_validator("differentiation_note")
    @classmethod
    def differentiation_note_is_trimmed(cls, value: str) -> str:
        """Trim Contributor explanation before writing audit metadata."""
        return value.strip()


class SimilarityNotice(BaseModel):
    """Non-blocking internal similarity notice for a processed Artifact."""

    jaccard: Decimal = Field(decimal_places=4)
    nearest_match_artifact_id: UUID | None = None
    nearest_match_framework_id: UUID | None = None
    nearest_match_title: str | None = None
    average_review_score: Decimal | None = Field(default=None, decimal_places=2)
    review_count: int = 0


class FrameworkVersionCreate(BaseModel):
    """Request body for starting a new draft version of a Framework."""

    change_type: ChangeType
    change_log: str = Field(min_length=1)
    artifact_inheritance: dict[UUID, bool] = Field(default_factory=dict)


class ArtifactFromConnectorRequest(BaseModel):
    """Import a connected-source file as a new draft Artifact."""

    connection_id: UUID
    file_id: str = Field(min_length=1, max_length=256)


class BindSourceRequest(BaseModel):
    """Owner request to bind (attach or repoint) an artifact to a connector file."""

    connection_id: UUID
    file_id: str = Field(min_length=1, max_length=256)


class ArtifactResponse(BaseModel):
    """Contributor-facing Artifact processing status."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    framework_id: UUID
    name: str
    file_key: str
    file_size: int
    mime_type: str
    source_kind: str
    scan_status: str
    processing_status: str
    pii_detected: bool
    pii_review_needed: bool
    pii_types_found: list[str] = []
    redaction_available: bool
    redaction_status: str | None
    redaction_accepted: bool
    rarity_score: Decimal | None
    near_duplicate_blocked: bool = False
    similarity_notice: SimilarityNotice | None = None
    created_at: datetime


class SourcePreviewResponse(BaseModel):
    """Owner-only, draft-only source preview response for a bound artifact."""

    model_config = ConfigDict(from_attributes=True)

    preview_url: str | None
    source_updated: bool
    source_last_synced_at: datetime | None


class FrameworkReviewCreate(BaseModel):
    """Request body for creating an Operator review of a licensed Framework."""

    score: int = Field(ge=1, le=5)
    body: str | None = Field(default=None, max_length=4000)

    @field_validator("body")
    @classmethod
    def body_is_trimmed(cls, value: str | None) -> str | None:
        """Normalize blank review text to null."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class FrameworkReviewUpdate(BaseModel):
    """Request body for editing the current Operator's Framework review."""

    score: int | None = Field(default=None, ge=1, le=5)
    body: str | None = Field(default=None, max_length=4000)

    @field_validator("body")
    @classmethod
    def body_is_trimmed(cls, value: str | None) -> str | None:
        """Normalize blank review text to null."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def has_editable_field(self) -> FrameworkReviewUpdate:
        """Require at least one review field to be patched."""
        if self.score is None and self.body is None:
            raise ValueError("At least one review field is required.")
        return self


class FrameworkReviewResponse(BaseModel):
    """Public review record written by a licensed Operator."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    framework_id: UUID
    operator_id: UUID | None
    reviewer_org_id: UUID | None
    score: int
    body: str | None
    created_at: datetime
    updated_at: datetime


class FrameworkReviewListResponse(BaseModel):
    """Review list and aggregate score for one Framework."""

    reviews: list[FrameworkReviewResponse]
    average_score: Decimal | None = Field(default=None, decimal_places=2)
    review_count: int
