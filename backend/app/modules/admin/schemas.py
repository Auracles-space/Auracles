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
    """Response body for an admin identity-verification override."""

    user_id: UUID
    kyc_status: str


class AdminFrameworkSuspendRequest(BaseModel):
    """Request body for post-publish Framework suspension."""

    reason: str = Field(min_length=1)


class AdminFrameworkStatusResponse(BaseModel):
    """Response body for admin Framework state changes."""

    framework_id: UUID
    status: str
    reason: str | None = None


class AdminSuspendedFrameworkItem(BaseModel):
    """One suspended Framework awaiting possible reinstatement."""

    framework_id: UUID
    title: str
    contributor_id: UUID
    contributor_name: str
    reason: str | None = None
    suspended_at: datetime | None = None


class AdminSuspendedFrameworksResponse(BaseModel):
    """Listing of Frameworks currently suspended from the marketplace."""

    items: list[AdminSuspendedFrameworkItem]


class AdminFrameworkDirectoryItem(BaseModel):
    """One Framework in the admin directory used to pick a delist target."""

    framework_id: UUID
    title: str
    contributor_id: UUID
    contributor_name: str
    status: str
    published_at: datetime | None = None


class AdminFrameworkDirectoryResponse(BaseModel):
    """Paginated admin listing of Frameworks for post-publish state control."""

    items: list[AdminFrameworkDirectoryItem]


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


class AdminUserDirectoryItem(BaseModel):
    """One user row visible in the admin account directory."""

    user_id: UUID
    display_name: str
    email: str
    roles: list[str]
    created_at: datetime
    suspended: bool
    suspended_at: datetime | None
    is_superadmin: bool = False
    kyc_status: str


class AdminUserDirectoryResponse(BaseModel):
    """Paginated admin user directory response."""

    items: list[AdminUserDirectoryItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


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
        "attestation_dispute_window_business_days",
        "saved_search_alert_cadence_hours",
        "consent_version_terms_of_service",
        "consent_version_privacy_policy",
        "account_deletion_grace_days",
        "data_export_expiry_days",
        "reputation_weights_framework",
        "reputation_weights_contributor",
        "reputation_weights_operator",
        "reputation_weights_attestor",
        "reputation_min_activity_framework",
        "reputation_min_activity_contributor",
        "reputation_min_activity_operator",
        "reputation_prior",
        "reputation_prior_strength_k",
        "reputation_dispute_penalty",
    ]
    value: str = Field(min_length=1, max_length=1000)


class AdminConfigPatchRequest(BaseModel):
    """Request body for audited platform configuration changes."""

    reason: str = Field(min_length=1, max_length=500)
    totp_code: str = Field(min_length=6, max_length=16)
    updates: list[AdminConfigUpdateItem] = Field(min_length=1, max_length=10)


class AdminReputationRecomputeRequest(BaseModel):
    """Request body for an audited single-subject reputation recompute."""

    subject_type: Literal["framework", "contributor", "operator", "attestor_org"]
    subject_id: UUID
    reason: str = Field(min_length=1, max_length=500)
    totp_code: str = Field(min_length=6, max_length=16)


class AdminReputationRecomputeResponse(BaseModel):
    """Acknowledgement that a recompute was queued."""

    status: str
    subject_type: str
    subject_id: UUID


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


class AdminPayoutItem(BaseModel):
    """One payout row for read-only admin oversight.

    Deliberately excludes payout-account details (``provider_account_id``): those
    are sensitive PII and never surface in an admin list per the PII rule. The
    provider label and transfer reference are enough to investigate a payout.
    """

    payout_id: UUID
    beneficiary_type: Literal["contributor", "org"]
    beneficiary_id: UUID
    provider: Literal["stripe", "paystack"]
    amount: str
    commission_deducted: str
    net_amount: str
    currency: str
    status: Literal["pending", "processing", "completed", "failed"]
    provider_ref: str | None
    initiated_at: datetime
    completed_at: datetime | None


class AdminPayoutDirectoryResponse(BaseModel):
    """Paginated payout directory for admin financial oversight."""

    items: list[AdminPayoutItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class AdminDeletionRequestItem(BaseModel):
    """One account-deletion request for the admin GDPR oversight queue."""

    request_id: UUID
    user_id: UUID
    status: Literal["pending", "scheduled", "blocked", "cancelled", "completed"]
    blocked_reasons: list[dict[str, Any]]
    scheduled_for: datetime | None
    requested_at: datetime
    completed_at: datetime | None


class AdminDeletionRequestsResponse(BaseModel):
    """Paginated account-deletion request queue for admins."""

    items: list[AdminDeletionRequestItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class AdminExportRequestItem(BaseModel):
    """One data-export request for the admin GDPR oversight queue.

    Excludes ``bundle_key`` — that is an internal S3 pointer to the user's
    personal export and must never surface in an admin list.
    """

    request_id: UUID
    user_id: UUID
    status: Literal["pending", "processing", "ready", "failed", "expired"]
    failure_reason: str | None
    requested_at: datetime
    completed_at: datetime | None
    expires_at: datetime | None


class AdminExportRequestsResponse(BaseModel):
    """Paginated data-export request queue for admins."""

    items: list[AdminExportRequestItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
