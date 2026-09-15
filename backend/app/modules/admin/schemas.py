"""Pydantic schemas for admin endpoints.

Defines request and response contracts for configuration, analytics, moderation,
and other back-office flows exposed under `/v1/admin/*`.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class AdminKycDocumentResponse(BaseModel):
    """Metadata for one identity document in the admin review queue.

    Carries no storage key: the file is reached only through the download
    endpoint, which checks the scan result and audits the access.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    doc_type: str
    mime_type: str
    file_size: int
    status: str
    scan_status: str
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    notes: str | None
    created_at: datetime


class AdminKycDocumentsResponse(BaseModel):
    """Identity documents a user has submitted for manual review."""

    user_id: UUID
    documents: list[AdminKycDocumentResponse]


class AdminKycDocumentDownloadResponse(BaseModel):
    """Short-lived presigned link to one identity document."""

    download_url: str
    expires_in: int


class AdminFrameworkSuspendRequest(BaseModel):
    """Request body for post-publish Framework suspension."""

    reason: str = Field(min_length=1)


class AdminFrameworkReinstateRequest(BaseModel):
    """Request body for reversing a Framework takedown.

    Intentionally empty: reinstatement takes no input, but returning a
    suspended Framework to the public catalog is a trust decision and the
    endpoint is step-up gated like its sibling takedown.
    """


class AdminFrameworkStatusResponse(BaseModel):
    """Response body for admin Framework state changes."""

    framework_id: UUID
    status: str
    reason: str | None = None


class AdminSuspendedFrameworkItem(BaseModel):
    """One suspended Framework awaiting possible reinstatement."""

    framework_id: UUID
    title: str
    # Exactly one seller owns a Framework (ck_frameworks_seller_xor): a
    # Contributor-owned row nulls the organization fields and vice versa.
    contributor_id: UUID | None = None
    contributor_name: str | None = None
    organization_id: UUID | None = None
    organization_name: str | None = None
    reason: str | None = None
    suspended_at: datetime | None = None


class AdminSuspendedFrameworksResponse(BaseModel):
    """Listing of Frameworks currently suspended from the marketplace."""

    items: list[AdminSuspendedFrameworkItem]


class AdminFrameworkDirectoryItem(BaseModel):
    """One Framework in the admin directory used to pick a delist target."""

    framework_id: UUID
    title: str
    # Exactly one seller owns a Framework (ck_frameworks_seller_xor): a
    # Contributor-owned row nulls the organization fields and vice versa.
    contributor_id: UUID | None = None
    contributor_name: str | None = None
    organization_id: UUID | None = None
    organization_name: str | None = None
    status: str
    published_at: datetime | None = None


class AdminFrameworkDirectoryResponse(BaseModel):
    """Paginated admin listing of Frameworks for post-publish state control."""

    items: list[AdminFrameworkDirectoryItem]


class AdminUserSuspendRequest(BaseModel):
    """Request body for suspending a user account."""

    reason: str = Field(min_length=1, max_length=1000)


class AdminUserUnsuspendRequest(BaseModel):
    """Request body for unsuspending a user account.

    Intentionally empty: the endpoint is step-up gated at the router and
    takes no other input.
    """


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
        "min_payout_ngn",
        "refund_window_hours",
        "attestation_fee_framework",
        "attestation_fee_contributor",
        "attestation_fee_operator",
        "attestation_fee_credential",
        "attestation_fee_review_quality",
        "attestation_fee_review_compliance",
        "attestation_fee_review_expert",
        "attestation_fee_review_provenance",
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
    updates: list[AdminConfigUpdateItem] = Field(min_length=1, max_length=10)


class AdminReputationRecomputeRequest(BaseModel):
    """Request body for an audited single-subject reputation recompute."""

    subject_type: Literal["framework", "contributor", "operator", "attestor_org"]
    subject_id: UUID
    reason: str = Field(min_length=1, max_length=500)


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
    # Exactly one seller owns a Framework (ck_frameworks_seller_xor): a
    # Contributor-owned row nulls the organization fields and vice versa.
    contributor_id: UUID | None = None
    contributor_name: str | None = None
    organization_id: UUID | None = None
    organization_name: str | None = None
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
    # Organization name for org payouts, display name for contributors.
    beneficiary_name: str | None = None
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


class AdminConnectorItem(BaseModel):
    """One external OAuth connection for admin oversight.

    Excludes the encrypted access/refresh tokens entirely — only the connection
    metadata (provider, connected account email, scopes, status) is exposed so
    admins can audit connection health and revocation state.
    """

    connection_id: UUID
    user_id: UUID
    provider: str
    provider_account_email: str | None
    scopes: str
    status: str
    token_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminConnectorsResponse(BaseModel):
    """Paginated external-connection directory for admin oversight."""

    items: list[AdminConnectorItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class AdminWaitlistItem(BaseModel):
    """One pre-launch waitlist signup for admin review."""

    entry_id: UUID
    email: str
    source: str | None
    created_at: datetime


class AdminWaitlistResponse(BaseModel):
    """Paginated waitlist directory for admins."""

    items: list[AdminWaitlistItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class AdminInvoiceItem(BaseModel):
    """One issued invoice for admin financial oversight.

    Excludes the internal ``s3_key`` PDF pointer — reconciliation only needs the
    invoice metadata, parties, and totals.
    """

    invoice_id: UUID
    invoice_number: str
    doc_type: str
    issue_date: datetime
    currency: str
    subtotal: str
    tax_amount: str
    total: str
    seller_name: str
    buyer_name: str
    buyer_email: str
    source_ref_type: str
    source_ref_id: UUID
    # Derived from the invoice source (attesting, paying, or paid org); null
    # when no organization is involved.
    organization_id: UUID | None = None
    organization_name: str | None = None
    created_at: datetime


class AdminInvoicesResponse(BaseModel):
    """Paginated issued-invoice directory for admins."""

    items: list[AdminInvoiceItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class AdminTransactionItem(BaseModel):
    """One transaction row for read-only admin financial oversight.

    Carries `failure_reason_code` from the newest ledger event so a failed
    payment is triageable from the list: `status` alone records only that it
    failed, never why.
    """

    transaction_id: UUID
    transaction_type: str
    status: str
    amount: str
    currency: str
    platform_commission: str
    net_amount: str
    provider: Literal["stripe", "paystack"] | None
    provider_ref: str | None
    payer_id: UUID | None
    payer_org_id: UUID | None
    payer_org_name: str | None = None
    payee_id: UUID | None
    payee_org_id: UUID | None
    payee_org_name: str | None = None
    ref_type: str | None
    ref_id: UUID | None
    failure_reason_code: str | None
    created_at: datetime
    updated_at: datetime


class AdminTransactionDirectoryResponse(BaseModel):
    """Paginated transaction directory for admin financial oversight."""

    items: list[AdminTransactionItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class AdminFinancialEventItem(BaseModel):
    """One immutable money state change from the financial ledger.

    `reason_code` is the provider-neutral cause; the raw provider code stays in
    `metadata`, which the ledger writer strips of sensitive keys before storing.
    """

    event_id: UUID
    entity_type: str
    entity_id: UUID
    event_type: str
    from_status: str | None
    to_status: str | None
    amount: str | None
    currency: str | None
    provider: Literal["stripe", "paystack"] | None
    provider_ref: str | None
    reason_code: str | None
    reason_message: str | None
    actor_id: UUID | None
    occurred_at: datetime
    metadata: dict[str, Any]


class AdminFinancialEventsResponse(BaseModel):
    """Paginated financial ledger feed for admin oversight."""

    items: list[AdminFinancialEventItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class AdminEscrowItem(BaseModel):
    """One escrow holding for admin financial oversight."""

    escrow_id: UUID
    transaction_id: UUID
    ref_type: str
    ref_id: UUID
    amount: str
    currency: str
    status: Literal["held", "released", "refunded"]
    held_at: datetime
    released_at: datetime | None
    released_by: UUID | None


class AdminTransactionDetailResponse(BaseModel):
    """One payment with its escrow holdings and full ledger timeline.

    The timeline is ordered oldest-first because it is read as a history: the
    status column keeps only the final value, so intermediate transitions exist
    nowhere else.
    """

    transaction: AdminTransactionItem
    escrows: list[AdminEscrowItem]
    timeline: list[AdminFinancialEventItem]


class AdminEscrowDirectoryResponse(BaseModel):
    """Paginated escrow directory for admin financial oversight."""

    items: list[AdminEscrowItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class AdminWebhookEventItem(BaseModel):
    """One provider webhook delivery for admin oversight.

    Exposes the stored `error`, which the ingest path writes on every failed
    delivery. The raw provider payload is never stored, only its hash, so a
    signed body cannot leak through this view.
    """

    event_id: UUID
    provider: Literal["stripe", "paystack"]
    provider_event_id: str
    event_type: str
    status: Literal["received", "processed", "failed"]
    error: str | None
    received_at: datetime
    processed_at: datetime | None


class AdminWebhookEventsResponse(BaseModel):
    """Paginated webhook delivery log for admin oversight."""

    items: list[AdminWebhookEventItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class AdminAuditLogItem(BaseModel):
    """One audit log entry for the admin oversight view."""

    log_id: UUID
    actor_id: UUID | None
    action: str
    target_type: str
    target_id: UUID | None
    metadata: dict[str, Any]
    created_at: datetime


class AdminAuditLogsResponse(BaseModel):
    """Paginated audit log view for admin oversight."""

    items: list[AdminAuditLogItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
