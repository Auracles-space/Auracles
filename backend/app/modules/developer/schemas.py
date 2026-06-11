"""Pydantic schemas for Developer platform endpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.modules.developer.constants import VALID_API_KEY_SCOPES


class DeveloperApplicationCreateRequest(BaseModel):
    """Request body for submitting a Developer role application."""

    company_name: str = Field(min_length=2, max_length=255)
    website: HttpUrl | None = None
    use_case: str = Field(min_length=20, max_length=5000)


class DeveloperApplicationResponse(BaseModel):
    """Developer application details visible to its owner and admins."""

    id: UUID
    user_id: UUID
    company_name: str
    website: str | None
    use_case: str
    status: str
    admin_feedback: str | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeveloperApplicationsResponse(BaseModel):
    """List response for Developer applications."""

    applications: list[DeveloperApplicationResponse]


class DeveloperApplicationReviewRequest(BaseModel):
    """Admin request body for approving or rejecting a Developer application."""

    decision: Literal["approved", "rejected"]
    feedback: str | None = Field(default=None, max_length=5000)
    totp_code: str = Field(min_length=6, max_length=16)


class ApiKeyCreateRequest(BaseModel):
    """Request body for creating a partner API key."""

    name: str = Field(min_length=1, max_length=255)
    scopes: list[str] = Field(min_length=1, max_length=20)
    expires_at: datetime | None = None

    @field_validator("scopes")
    @classmethod
    def scopes_are_known_and_unique(cls, value: list[str]) -> list[str]:
        """Reject duplicate or unknown API key scopes."""
        if len(set(value)) != len(value):
            raise ValueError("Scopes must be unique.")
        unknown = sorted(set(value) - VALID_API_KEY_SCOPES)
        if unknown:
            raise ValueError(f"Unknown API key scopes: {', '.join(unknown)}.")
        return value


class ApiKeyUpdateRequest(BaseModel):
    """Request body for changing an API key display label."""

    name: str = Field(min_length=1, max_length=255)


class ApiKeyResponse(BaseModel):
    """API key metadata returned after creation, listing, update, or revoke."""

    id: UUID
    name: str
    key_prefix: str
    scopes: list[str]
    status: str
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreateResponse(ApiKeyResponse):
    """API key creation response that includes the raw key exactly once."""

    raw_key: str


class ApiKeysResponse(BaseModel):
    """List response for API key metadata."""

    api_keys: list[ApiKeyResponse]


class PartnerFrameworkDetailResponse(BaseModel):
    """Partner-safe public Framework detail without full artifact inventory."""

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
    average_review_score: Decimal | None = None
    review_count: int = 0
    attestation_badge: dict[str, object] | None = None
    published_at: datetime | None
    preview_artifact_id: UUID | None


class PartnerPreviewArtifactResponse(BaseModel):
    """Partner-safe preview Artifact payload with a temporary preview URL."""

    id: UUID
    name: str
    file_size: int
    mime_type: str
    preview_url: str
    created_at: datetime


class PartnerAttestationReportResponse(BaseModel):
    """Public Attestation report metadata exposed through Partner API."""

    id: UUID
    status: str
    outcome: str
    report_key: str
    issued_at: datetime | None


class PartnerAttestationsResponse(BaseModel):
    """List response for public Partner Attestation report metadata."""

    attestations: list[PartnerAttestationReportResponse]
