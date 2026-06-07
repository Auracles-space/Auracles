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

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
LicenseType = Literal["single_user", "team", "enterprise"]
OrgSize = Literal["startup", "small_business", "sme", "mid_market", "enterprise"]
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class PricingConfig(BaseModel):
    """Framework pricing and licensing options configured by a Contributor."""

    price: Decimal = Field(gt=0, decimal_places=2, max_digits=12)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    license_types: list[LicenseType] = Field(min_length=1)
    commercial_rights: str | None = None
    usage_restrictions: str | None = None

    @field_validator("currency")
    @classmethod
    def currency_is_uppercase_iso_code(cls, value: str) -> str:
        """Normalize ISO-like currency codes to uppercase three-letter text."""
        return value.upper()


class FrameworkCreate(BaseModel):
    """Request body for creating a draft Framework."""

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    category: str = Field(min_length=1, max_length=100)
    sector: str | None = Field(default=None, max_length=100)
    industry: str | None = Field(default=None, max_length=100)
    function: str | None = Field(default=None, max_length=100)
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
    category: str | None = Field(default=None, min_length=1, max_length=100)
    sector: str | None = Field(default=None, max_length=100)
    industry: str | None = Field(default=None, max_length=100)
    function: str | None = Field(default=None, max_length=100)
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


class FrameworkResponse(BaseModel):
    """Contributor-facing Framework representation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contributor_id: UUID
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
