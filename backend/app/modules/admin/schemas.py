"""Pydantic schemas for admin endpoints.

Defines request and response contracts for configuration, analytics, moderation,
and other back-office flows exposed under `/v1/admin/*`.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AdminRoleAssignmentRequest(BaseModel):
    """Request body for assigning or approving a user role."""

    role: Literal["contributor", "operator", "attestor", "admin"]


class AdminRoleAssignmentResponse(BaseModel):
    """Response body for admin role assignment."""

    user_id: UUID
    role: str
    approved: bool


class AdminKycReviewRequest(BaseModel):
    """Request body for admin KYC review decisions."""

    status: Literal["verified", "rejected"]
    notes: str | None = None


class AdminKycReviewResponse(BaseModel):
    """Response body for admin KYC review."""

    user_id: UUID
    kyc_status: str
    document_status: str


class AdminFrameworkSuspendRequest(BaseModel):
    """Request body for post-publish Framework suspension."""

    reason: str = Field(min_length=1)


class AdminFrameworkStatusResponse(BaseModel):
    """Response body for admin Framework state changes."""

    framework_id: UUID
    status: str
    reason: str | None = None


class AdminUserSuspendRequest(BaseModel):
    """Request body for suspending a user account."""

    reason: str = Field(min_length=1, max_length=1000)
    totp_code: str = Field(min_length=6, max_length=16)


class AdminUserUnsuspendRequest(BaseModel):
    """Request body for unsuspending a user account."""

    totp_code: str = Field(min_length=6, max_length=16)


class AdminUserSuspensionResponse(BaseModel):
    """Response body for admin user suspension lifecycle changes."""

    user_id: UUID
    suspended: bool
    suspended_at: datetime | None
    suspended_by: UUID | None
    suspension_reason: str | None


class AdminRarityBlockOverrideRequest(BaseModel):
    """Request body for overriding a near-duplicate rarity hard block."""

    reason: str = Field(min_length=5, max_length=1000)


class AdminLicenseGrantRequest(BaseModel):
    """Request body for admin-mediated license grants."""

    framework_id: UUID
    operator_id: UUID
    type: Literal["single_user", "team", "organizational", "enterprise"]
    expires_at: datetime | None = None
    seats_total: int | None = Field(default=None, ge=1)


class AdminLicenseGrantResponse(BaseModel):
    """Response body for an admin-created license."""

    license_id: UUID
    framework_id: UUID
    operator_id: UUID
    type: str
    status: str
    version_at_grant: str
    seats_used: int
    seats_total: int | None
    expires_at: datetime | None


class AdminEscrowOverrideRequest(BaseModel):
    """Request body for admin escrow release or refund overrides."""

    reason: str = Field(min_length=1)
    totp_code: str = Field(min_length=6, max_length=16)


class AdminEscrowResponse(BaseModel):
    """Response body for admin escrow state changes."""

    escrow_id: UUID
    transaction_id: UUID
    ref_id: UUID
    ref_type: str
    amount: str
    currency: str
    status: str
    released_at: datetime | None
    released_by: UUID | None


class AdminDisputeResolveRequest(BaseModel):
    """Request body for resolving a Project dispute."""

    resolution_type: Literal["release", "refund", "split"]
    release_amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
    )
    refund_amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
    )
    resolution_notes: str = Field(min_length=5, max_length=4000)
    totp_code: str = Field(min_length=6, max_length=16)


class AdminConfigItem(BaseModel):
    """Single platform configuration value visible to administrators."""

    key: str
    value: str
    editable: bool
    updated_at: datetime
    updated_by: UUID | None


class AdminConfigResponse(BaseModel):
    """Response body for admin platform configuration reads and writes."""

    items: list[AdminConfigItem]


class AdminConfigUpdateItem(BaseModel):
    """Single admin platform configuration change request."""

    key: Literal[
        "commission_rate",
        "min_payout_usd",
        "refund_window_hours",
        "attestation_fee_framework",
        "attestation_fee_contributor",
        "attestation_fee_operator",
        "attestation_fee_credential",
        "attestation_cohort_size",
        "attestation_completion_sla_days_framework",
        "attestation_completion_sla_days_contributor",
        "attestation_completion_sla_days_operator",
        "attestation_completion_sla_days_credential",
        "attestation_offer_accept_hours",
        "attestation_dispute_window_days",
        "saved_search_alert_cadence_hours",
        "consent_version_terms_of_service",
        "consent_version_privacy_policy",
        "account_deletion_grace_days",
        "data_export_expiry_days",
    ]
    value: str = Field(min_length=1, max_length=100)


class AdminConfigPatchRequest(BaseModel):
    """Request body for audited platform configuration changes."""

    reason: str = Field(min_length=1, max_length=500)
    totp_code: str = Field(min_length=6, max_length=16)
    updates: list[AdminConfigUpdateItem] = Field(min_length=1, max_length=10)


class AdminAnalyticsGmvBreakdown(BaseModel):
    """Money totals for each marketplace revenue source within one window."""

    framework_purchase: str
    collection_purchase: str
    project_milestone: str
    attestation_fee: str


class AdminAnalyticsGmvResponse(BaseModel):
    """GMV totals and by-source breakdowns for the admin dashboard."""

    today_total: str
    last_7_days_total: str
    last_30_days_total: str
    today_by_source: AdminAnalyticsGmvBreakdown
    last_7_days_by_source: AdminAnalyticsGmvBreakdown
    last_30_days_by_source: AdminAnalyticsGmvBreakdown


class AdminAnalyticsWindowCounts(BaseModel):
    """Three standard recency windows used across current-state analytics."""

    last_24_hours: int
    last_7_days: int
    last_30_days: int


class AdminAnalyticsPublishedFrameworks(BaseModel):
    """Published Framework totals and recent publication counts."""

    total: int
    last_24_hours: int
    last_7_days: int
    last_30_days: int


class AdminAnalyticsDisputesOpen(BaseModel):
    """Current open dispute counts split by dispute source."""

    total: int
    projects: int
    attestations: int


class AdminAnalyticsTrendPoint(BaseModel):
    """One frozen UTC daily analytics row for dashboard trend charts."""

    snapshot_date: date
    gmv_total: str
    active_users: int
    new_registrations: int
    frameworks_published: int
    attestations_issued: int
    disputes_open: int


class AdminAnalyticsDashboardResponse(BaseModel):
    """Current-state admin analytics plus frozen historical trend rows."""

    gmv: AdminAnalyticsGmvResponse
    active_users: AdminAnalyticsWindowCounts
    new_registrations: AdminAnalyticsWindowCounts
    frameworks_published: AdminAnalyticsPublishedFrameworks
    attestations_issued: AdminAnalyticsWindowCounts
    disputes_open: AdminAnalyticsDisputesOpen
    trend: list[AdminAnalyticsTrendPoint]


class AdminModerationActionLink(BaseModel):
    """Existing API action relevant to one moderation queue row."""

    rel: str
    method: Literal["POST"]
    path: str
    actor_role: Literal["admin", "contributor"]


class AdminModerationQueueItem(BaseModel):
    """One moderation queue row aggregated from existing platform signals."""

    signal_id: str
    queue_type: Literal["rarity_review", "near_duplicate_block", "pii_review"]
    framework_id: UUID
    framework_title: str
    contributor_id: UUID
    contributor_name: str
    artifact_id: UUID | None = None
    artifact_name: str | None = None
    signal_at: datetime
    details: dict[str, Any]
    action_links: list[AdminModerationActionLink]


class AdminModerationQueueResponse(BaseModel):
    """Paginated moderation queue response for admin review surfaces."""

    items: list[AdminModerationQueueItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
