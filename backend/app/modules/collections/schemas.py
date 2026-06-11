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

CollectionStatus = Literal["draft", "published", "unpublished"]


class CollectionCreateRequest(BaseModel):
    """Contributor request body for creating a draft Collection."""

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    bundle_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def currency_must_be_usd(cls, value: str) -> str:
        """Reject non-USD Collections during the MVP currency lock."""
        if value.upper() != "USD":
            raise ValueError("Collection currency must be USD.")
        return value.upper()


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
    def currency_must_be_usd(cls, value: str | None) -> str | None:
        """Reject non-USD Collection edits during the MVP currency lock."""
        if value is None:
            return None
        if value.upper() != "USD":
            raise ValueError("Collection currency must be USD.")
        return value.upper()


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
