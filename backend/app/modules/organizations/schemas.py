"""Pydantic schemas for Organizations Core."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrganizationCreateRequest(BaseModel):
    """Request body to create an organization."""

    slug: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9-]+$")
    name: str = Field(min_length=2, max_length=120)
    country: str = Field(min_length=2, max_length=2)
    website: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        """Normalize slugs to lowercase and trim surrounding whitespace."""
        return value.strip().lower()

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        """Normalize country codes to uppercase ISO-3166-1 alpha-2 form."""
        return value.strip().upper()

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        """Trim organization names before persistence."""
        return value.strip()

    @field_validator("website", "description")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        """Trim optional text fields while preserving nulls."""
        return value.strip() if value is not None else None


class OrganizationResponse(BaseModel):
    """Public-safe organization fields."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    logo_key: str | None
    country: str
    website: str | None
    description: str | None
    created_at: datetime


class MyOrganizationResponse(BaseModel):
    """An organization membership visible to the current user."""

    org: OrganizationResponse
    role: str
    capabilities: dict[str, str]


class MyOrganizationsResponse(BaseModel):
    """List wrapper for the authenticated user's organizations."""

    organizations: list[MyOrganizationResponse]
