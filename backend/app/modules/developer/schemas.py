"""Pydantic schemas for Developer platform endpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator

from app.modules.developer.constants import (
    VALID_API_KEY_SCOPES,
    VALID_PARTNER_WEBHOOK_EVENTS,
)
from app.modules.financials.schemas import SelfServeLicenseType


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


class PartnerTierResponse(BaseModel):
    """Configured Partner tier range and commission rate."""

    tier: int
    min_sales: int
    max_sales: int | None
    rate: Decimal


class DeveloperTierProgressResponse(BaseModel):
    """Developer-facing current commission tier and next-tier progress."""

    current_tier: int
    current_rate: Decimal
    prior_30d_sales_count: int
    next_tier: int | None
    next_tier_sales_required: int | None
    tier_recalculated_at: datetime | None
    tiers: list[PartnerTierResponse]


class PartnerPayoutRequest(BaseModel):
    """Request body for withdrawing cleared Partner commissions."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    payout_account_id: UUID
    totp_code: str = Field(min_length=6, max_length=16)


class PartnerPayoutResponse(BaseModel):
    """Developer-facing Partner payout request and processing status."""

    id: UUID
    payout_account_id: UUID
    amount: Decimal
    currency: str
    status: str
    provider_ref: str | None
    initiated_at: datetime
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class PartnerPayoutsResponse(BaseModel):
    """Response body for Partner payout history."""

    payouts: list[PartnerPayoutResponse]


class PartnerWebhookCreateRequest(BaseModel):
    """Request body for registering a Partner outbound webhook endpoint."""

    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    events: list[str] = Field(min_length=1, max_length=20)

    @field_validator("url")
    @classmethod
    def webhook_url_is_https(cls, value: HttpUrl) -> HttpUrl:
        """Require HTTPS webhook endpoints before storing Partner URLs."""
        if value.scheme != "https":
            raise ValueError("Webhook URL must use https.")
        return value

    @field_validator("events")
    @classmethod
    def events_are_known_and_unique(cls, value: list[str]) -> list[str]:
        """Reject duplicate or unknown Partner webhook event names."""
        if len(set(value)) != len(value):
            raise ValueError("Webhook events must be unique.")
        unknown = sorted(set(value) - VALID_PARTNER_WEBHOOK_EVENTS)
        if unknown:
            raise ValueError(f"Unknown webhook events: {', '.join(unknown)}.")
        return value


class PartnerWebhookResponse(BaseModel):
    """Partner webhook endpoint metadata with a masked signing-secret hint.

    The full secret is only returned once on creation; ``secret_hint`` is a
    non-sensitive masked form (prefix + last four characters) shown in the list
    so the partner can recognize which secret is configured.
    """

    id: UUID
    url: str
    events: list[str]
    active: bool
    created_at: datetime
    secret_hint: str

    model_config = ConfigDict(from_attributes=True)


class PartnerWebhookCreateResponse(PartnerWebhookResponse):
    """Webhook creation response that includes the raw secret exactly once."""

    secret: str


class PartnerWebhooksResponse(BaseModel):
    """List response for Partner webhook endpoint metadata."""

    webhooks: list[PartnerWebhookResponse]


class PartnerWebhookDeliveryResponse(BaseModel):
    """Developer-facing outbound webhook delivery state."""

    id: UUID
    partner_webhook_id: UUID
    event_type: str
    status: str
    attempts: int
    response_code: int | None
    last_attempt_at: datetime | None
    next_attempt_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeveloperUsageEndpointBreakdown(BaseModel):
    """Aggregated Partner API usage for one endpoint/method pair."""

    endpoint: str
    method: str
    request_count: int
    success_count: int
    client_error_count: int
    server_error_count: int
    average_response_ms: int


class DeveloperUsageAnalyticsResponse(BaseModel):
    """Developer-facing Partner API usage analytics response."""

    window_days: int
    total_requests: int
    success_count: int
    client_error_count: int
    server_error_count: int
    average_response_ms: int
    by_endpoint: list[DeveloperUsageEndpointBreakdown]


class DeveloperSalesFrameworkBreakdown(BaseModel):
    """Aggregated Partner sales for one attributed Framework."""

    framework_id: UUID
    framework_title: str
    sale_count: int
    gross_sale_amount: Decimal
    commission_amount: Decimal


class DeveloperSalesAnalyticsResponse(BaseModel):
    """Developer-facing Partner sales and commission analytics response."""

    window_days: int
    total_sales: int
    gross_sale_amount: Decimal
    total_commission_amount: Decimal
    pending_commission_amount: Decimal
    cleared_commission_amount: Decimal
    paid_commission_amount: Decimal
    voided_commission_amount: Decimal
    status_counts: dict[str, int]
    by_framework: list[DeveloperSalesFrameworkBreakdown]


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


class PartnerPurchaseRequest(BaseModel):
    """Partner request body for initiating checkout for a buyer email."""

    model_config = ConfigDict(extra="forbid")

    buyer_email: EmailStr
    license_type: SelfServeLicenseType


class PartnerPurchaseResponse(BaseModel):
    """Stripe checkout data returned to a Partner API purchase request."""

    transaction_id: UUID
    provider: Literal["stripe"]
    client_secret: str


class PartnerPurchaseStatusResponse(BaseModel):
    """Partner-visible purchase status without licensed artifact access."""

    transaction_id: UUID
    status: str
    provider: Literal["stripe"]
    framework_id: UUID
    buyer_email: EmailStr
    license_type: str
    amount: Decimal
    currency: str
