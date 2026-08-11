"""Pydantic schemas for contributor Collection CRUD.

Slice 2 exposes owner-scoped collection creation, editing, membership, publish,
and unpublish responses. Public Explore collection schemas arrive in Slice 3.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.currency import normalize_platform_currency, platform_currency

CollectionStatus = Literal["draft", "published", "unpublished"]


class CollectionCreateRequest(BaseModel):
    """Contributor request body for creating a draft Collection."""

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    bundle_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(
        default_factory=platform_currency,
        min_length=3,
        max_length=3,
    )

    @field_validator("currency")
    @classmethod
    def currency_is_the_platform_currency(cls, value: str) -> str:
        """Pin Collection pricing to the platform's settlement currency."""
        return normalize_platform_currency(value)


class CollectionUpdateRequest(BaseModel):
    """Contributor request body for editing an unpublished Collection."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    bundle_price: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
    )
    currency: str | None = Field(default=None, min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def currency_is_the_platform_currency(cls, value: str | None) -> str | None:
        """Pin edited Collection pricing to the platform's currency."""
        if value is None:
            return None
        return normalize_platform_currency(value)


class CollectionMemberRequest(BaseModel):
    """Contributor request body for adding one Framework to a Collection."""

    framework_id: UUID


class CollectionMemberResponse(BaseModel):
    """Framework summary embedded in contributor Collection responses."""

    framework_id: UUID
    title: str
    status: str
    price: Decimal
    currency: str


class CollectionResponse(BaseModel):
    """Contributor-facing Collection response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contributor_id: UUID
    title: str
    description: str
    bundle_price: Decimal
    currency: str
    status: CollectionStatus
    members: list[CollectionMemberResponse]
    created_at: datetime
    updated_at: datetime


class CollectionListResponse(BaseModel):
    """List response for Contributor-owned Collections."""

    collections: list[CollectionResponse]
