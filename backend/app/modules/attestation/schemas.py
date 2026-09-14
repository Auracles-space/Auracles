"""Pydantic schemas for Attestation and Attestor endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

IssuerType = Literal["institution", "organisation", "government", "association"]


class CoiEntry(BaseModel):
    """One declared conflict-of-interest relationship disclosed by an applicant.

    ``subject_id`` optionally links the declaration to a known platform entity
    so the matching engine can screen exact conflicts without relying on
    brittle free-text matching.
    """

    entity: str
    entity_type: Literal["firm", "fund", "individual"]
    relationship: Literal["financial", "advisory", "employment"]
    within_24mo: bool
    subject_id: UUID | None = None
    subject_kind: Literal["user", "framework"] | None = None


class ClarificationCreateRequest(BaseModel):
    """Request body for sending one attestation clarification question."""

    question: str = Field(min_length=1, max_length=5000)


class ClarificationRespondRequest(BaseModel):
    """Request body for responding to one attestation clarification."""

    response: str = Field(min_length=1, max_length=5000)


class ClarificationResponse(BaseModel):
    """One persisted attestation clarification row."""

    id: UUID
    attestation_id: UUID
    question: str
    response: str | None
    sent_at: datetime
    response_due_at: datetime
    responded_at: datetime | None
    status: str

    model_config = ConfigDict(from_attributes=True)


class CredentialCreateRequest(BaseModel):
    """Request body for creating a user-owned Credential."""

    title: str = Field(min_length=1, max_length=255)
    issuer: str = Field(min_length=1, max_length=255)
    issued_date: date
    expires_date: date | None = None
    credential_type: str | None = Field(default=None, max_length=255)
    verification_url: str | None = Field(default=None, max_length=2048)
    reference_number: str | None = Field(default=None, max_length=255)
    issuer_type: IssuerType | None = None

    @field_validator("expires_date")
    @classmethod
    def expiry_must_follow_issue_date(
        cls,
        value: date | None,
        info: Any,
    ) -> date | None:
        """Reject credentials whose expiry date predates the issued date."""
        issued_date = info.data.get("issued_date")
        if value is not None and issued_date is not None and value < issued_date:
            raise ValueError("expires_date must be after issued_date.")
        return value


class CredentialUpdateRequest(BaseModel):
    """Request body for updating a user-owned Credential."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    issuer: str | None = Field(default=None, min_length=1, max_length=255)
    issued_date: date | None = None
    expires_date: date | None = None
    credential_type: str | None = Field(default=None, max_length=255)
    verification_url: str | None = Field(default=None, max_length=2048)
    reference_number: str | None = Field(default=None, max_length=255)
    issuer_type: IssuerType | None = None
    evidence_file_keys: list[str] | None = Field(default=None, max_length=20)


class CredentialResponse(BaseModel):
    """Credential details returned to the owner."""

    id: UUID
    user_id: UUID
    title: str
    issuer: str
    issued_date: date
    expires_date: date | None
    evidence_file_keys: list[str]
    credential_type: str | None
    verification_url: str | None
    reference_number: str | None
    issuer_type: str | None
    verification_status: str
    submitted_at: datetime | None
    verified_at: datetime | None
    reviewed_by: UUID | None
    rejection_reason: str | None
    expired: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CredentialsResponse(BaseModel):
    """List response for user-owned Credentials."""

    credentials: list[CredentialResponse]


class CredentialEvidenceUploadCreateRequest(BaseModel):
    """Request body for creating a Credential evidence upload session."""

    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)


class CredentialEvidenceUploadSessionResponse(BaseModel):
    """Presigned POST response for a Credential evidence upload."""

    id: UUID
    s3_key: str
    url: str
    fields: dict[str, str]
    expires_at: datetime
    size_limit: int
    scan_status: str


class CredentialEvidenceDownloadResponse(BaseModel):
    """Presigned GET URL for one Credential evidence file."""

    url: str


class AttestationEvidenceUploadCreateRequest(BaseModel):
    """Request body for creating an Attestation report evidence upload session."""

    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)


class AttestationEvidenceUploadSessionResponse(BaseModel):
    """Presigned POST response for private Attestation report evidence."""

    id: UUID
    s3_key: str
    url: str
    fields: dict[str, str]
    expires_at: datetime
    size_limit: int
    scan_status: str


class AttestationReportSubmitRequest(BaseModel):
    """Structured report fields submitted by the assigned Attestor."""

    outcome: Literal["approved", "conditional", "rejected"]
    # Required, non-empty fields. Report body length is governed solely by the
    # quality gate's word minimum (rubric comments + summary + conditions), so
    # these carry no competing character floor beyond "must be present".
    summary: str = Field(min_length=1, max_length=10000)
    scope: str = Field(min_length=1, max_length=10000)
    conditions: str | None = Field(default=None, max_length=10000)
    evidence_references: dict[str, Any] = Field(default_factory=dict)


class RubricScoreUpsertRequest(BaseModel):
    """Draft score and comment for one rubric dimension."""

    score: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=5000)


class RubricScoreResponse(BaseModel):
    """One persisted attestation rubric-score row."""

    dimension_id: UUID
    score: int | None
    comment: str | None

    model_config = ConfigDict(from_attributes=True)


class RubricScoreItem(BaseModel):
    """One saved rubric score keyed by its stable dimension key.

    Used to rehydrate the workspace rubric panel on reload, matching the
    frontend's static dimension keys rather than internal dimension ids.
    """

    dimension_key: str
    score: int | None
    comment: str | None

    model_config = ConfigDict(from_attributes=True)


class RubricDimensionItem(BaseModel):
    """One rubric dimension the workspace scores, served with the scores.

    Lets the rubric panel render from the seeded definition instead of a
    client-side copy that can drift from the quality gate and the report.
    """

    key: str
    label: str
    weight: float
    display_order: int

    model_config = ConfigDict(from_attributes=True)


class RubricScoresResponse(BaseModel):
    """The workspace rubric definition and all saved scores for it."""

    dimensions: list[RubricDimensionItem] = Field(default_factory=list)
    scores: list[RubricScoreItem]


class RequestorRubricItem(BaseModel):
    """One rubric dimension result shown to the requestor on a submitted report.

    Unlike the workspace view (keyed for rehydration), this carries the human
    dimension label so the requestor sees a readable scorecard when deciding
    whether to accept or dispute.
    """

    dimension_key: str
    label: str
    score: int | None = None
    comment: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RequestorReportRubricResponse(BaseModel):
    """The attestor's rubric scorecard exposed to the report's requestor."""

    scores: list[RequestorRubricItem]


class AnnotationCreateRequest(BaseModel):
    """Request body for creating one free-anchor workspace annotation."""

    artifact_id: UUID | None = None
    location_label: str = Field(min_length=1, max_length=500)
    quoted_excerpt: str | None = Field(default=None, max_length=5000)
    annotation_type: Literal[
        "endorsement",
        "concern",
        "jurisdictional_caveat",
        "revision_recommended",
    ]
    comment: str = Field(min_length=1, max_length=5000)


class AnnotationUpdateRequest(AnnotationCreateRequest):
    """Request body for replacing a workspace annotation's editable fields."""


class AnnotationResponse(BaseModel):
    """One persisted attestation annotation row."""

    id: UUID
    artifact_id: UUID | None
    location_label: str
    quoted_excerpt: str | None
    annotation_type: str
    comment: str

    model_config = ConfigDict(from_attributes=True)


class AttestationDisputeCreateRequest(BaseModel):
    """Request body for raising an Attestation report dispute."""

    category: Literal[
        "scope_error",
        "process_violation",
        "material_inaccuracy",
        "conflict_of_interest",
    ]
    reason: str = Field(min_length=5, max_length=4000)


class AttestationAcceptRequest(BaseModel):
    """Attestor acceptance with the binding content-use acknowledgment."""

    content_ack: bool
    ack_version: str = Field(min_length=1, max_length=50)


class AttestationDisputeResponse(BaseModel):
    """Attestation dispute details visible to requestors and admins."""

    id: UUID
    attestation_id: UUID
    raised_by: UUID
    category: str
    reason: str
    status: str
    outcome: str | None
    is_complex: bool
    resolution_due_at: datetime | None
    admin_id: UUID | None
    resolution_notes: str | None
    escalated_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminAttestationDisputeListItem(BaseModel):
    """One Attestation dispute in the admin triage queue.

    Carries the attestation context an admin needs to judge the dispute in
    place — which org attested, what the request was, and how much escrow is at
    stake — so the queue does not force a second lookup per row. The requester's
    identity is deliberately absent: the verdict turns on the report, and list
    endpoints do not carry user PII.
    """

    id: UUID
    attestation_id: UUID
    category: str
    reason: str
    status: str
    outcome: str | None
    is_complex: bool
    resolution_due_at: datetime | None
    escalated_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    attestation_status: str
    review_type: str | None
    fee_amount: Decimal | None
    currency: str | None
    attestor_org_id: UUID | None
    attestor_org_name: str | None

    model_config = ConfigDict(from_attributes=True)


class AdminAttestationDisputesResponse(BaseModel):
    """Admin triage queue of Attestation disputes."""

    disputes: list[AdminAttestationDisputeListItem]


class AdminAttestationDisputeResolveRequest(BaseModel):
    """Admin request body for resolving an Attestation dispute.

    Module 5 replaces the old release/refund/split money-split model with a
    three-outcome verdict: reject the dispute (report stands, release escrow),
    uphold with a refund, or uphold requiring the attestor to revise.
    """

    outcome: Literal["rejected", "upheld_refund", "upheld_revise"]
    resolution_notes: str = Field(min_length=5, max_length=4000)
    is_complex: bool = False


class AdminAttestationAssignRequest(BaseModel):
    """Admin request body for dispatching a needs-admin Attestation to an org.

    The admin picks the attestor organization only. The org then accepts the
    offer and staffs its own reviewing member through the normal offer flow.
    """

    attestor_org_id: UUID
    reason: str = Field(min_length=5, max_length=4000)


class AdminAttestationRefundRequest(BaseModel):
    """Admin request body for refunding a needs-admin Attestation."""

    reason: str = Field(min_length=5, max_length=4000)


class AttestationBrief(BaseModel):
    """Structured review brief shown to the cohort during the offer phase."""

    what_it_does: str = Field(min_length=1, max_length=2000)
    use_case: str = Field(min_length=1, max_length=2000)
    jurisdiction: str = Field(min_length=1, max_length=200)
    focus_areas: str = Field(min_length=1, max_length=2000)
    desired_outcome: str = Field(min_length=1, max_length=2000)


class AttestationRequestCreateRequest(BaseModel):
    """Request body for creating an escrow-funded Attestation request."""

    target_type: Literal["framework", "contributor", "operator", "credential"]
    target_id: UUID
    review_type: Literal["quality", "compliance", "expert", "provenance"] | None = None
    brief: AttestationBrief | None = None
    requested_specializations: list[str] = Field(default_factory=list, max_length=25)
    requested_jurisdictions: list[str] = Field(default_factory=list, max_length=25)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    """ISO 3166-1 alpha-2 country of the payer, used to pick the payment rail.

    Optional: an omitted value routes to the default (Stripe) rail — the same
    shape self-serve checkout's `PurchaseRequest.country` uses.
    """

    @model_validator(mode="after")
    def require_lists_for_non_framework(self) -> AttestationRequestCreateRequest:
        """Require explicit matching lists for non-framework targets only."""
        if self.target_type != "framework":
            if not self.requested_specializations:
                raise ValueError("requested_specializations is required.")
            if not self.requested_jurisdictions:
                raise ValueError("requested_jurisdictions is required.")
        return self


class AttestationDisputeSummary(BaseModel):
    """The latest dispute on an attestation, as both parties may see it.

    Carries the requestor's stated reason and, once decided, the admin's
    outcome and notes. Never includes the admin's identity.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    category: str
    reason: str
    outcome: str | None = None
    resolution_notes: str | None = None
    resolution_due_at: datetime | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class AttestationRequestResponse(BaseModel):
    """Attestation request details visible to requestor and assigned Attestor."""

    id: UUID
    target_type: str
    target_id: UUID
    # Framework title when the target is a framework; lets cards and headers
    # name the thing under review instead of an id.
    target_title: str | None = None
    requestor_id: UUID
    attestor_org_id: UUID | None
    # Public directory name of the staffed attestor org, so the requestor
    # knows who is reviewing them.
    attestor_org_name: str | None = None
    status: str
    outcome: str | None
    review_type: str | None = None
    brief: dict[str, Any] | None = None
    requested_specializations: list[str]
    requested_jurisdictions: list[str]
    summary: str | None = None
    scope: str | None = None
    evidence_references: dict[str, Any] | None = None
    report_key: str | None = None
    fee_amount: Decimal
    currency: str
    escrow_id: UUID | None
    accepted_at: datetime | None = None
    completion_due_at: datetime | None = None
    issued_at: datetime | None = None
    dispute_window_ends_at: datetime | None = None
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # True when a clarification is awaiting the requestor's answer. Drives the
    # requestor list card's attention indicator; not an ORM column.
    open_clarification: bool = False
    # Latest dispute, populated on the detail view only.
    dispute: AttestationDisputeSummary | None = None
    # Platform-configured evidence floor for raising a dispute, populated on
    # the detail view so the decision form validates against the live value.
    dispute_evidence_min_length: int | None = None

    model_config = ConfigDict(from_attributes=True)


class AttestationsResponse(BaseModel):
    """List response for Attestations visible to the authenticated user."""

    attestations: list[AttestationRequestResponse]


class AdminAttestationOfferItem(BaseModel):
    """One offer made for an Attestation, with the recipient org's name.

    Admin oversight only: exposes which org an Attestation was offered to (or
    accepted by) and the offer lifecycle timestamps.
    """

    model_config = ConfigDict(from_attributes=True)

    org_id: UUID | None
    org_name: str | None
    status: str
    cohort_index: int
    offered_at: datetime
    expires_at: datetime
    responded_at: datetime | None
    decline_reason: str | None = None


class AdminAttestationDetailResponse(BaseModel):
    """Admin detail for one Attestation: the request plus its offer history."""

    attestation: AttestationRequestResponse
    offers: list[AdminAttestationOfferItem]


class AttestorAssignmentResponse(BaseModel):
    """Attestation offer or assignment visible to an approved Attestor."""

    offer_id: UUID
    attestation_id: UUID
    target_type: str
    target_id: UUID
    attestation_status: str
    offer_status: str
    cohort_index: int
    requestor_flagged: bool
    requested_specializations: list[str]
    requested_jurisdictions: list[str]
    expires_at: datetime
    accepted_at: datetime | None
    completion_due_at: datetime | None


class AttestorAssignmentsResponse(BaseModel):
    """List response for an Attestor's open offers and accepted work."""

    assignments: list[AttestorAssignmentResponse]


class AttestationFundingRequest(BaseModel):
    """Optional request body for funding an owner-approved Attestation fee."""

    model_config = ConfigDict(extra="forbid")

    country: str | None = Field(default=None, min_length=2, max_length=2)
    """ISO 3166-1 alpha-2 country of the payer, used to pick the payment rail."""


class AttestationFundingResponse(BaseModel):
    """Provider handle needed to complete paying an Attestation fee.

    Exactly one of the provider fields is set: Stripe returns a
    `client_secret` for the in-page PaymentElement, Paystack returns an
    `authorization_url` to redirect the browser to.
    """

    id: UUID
    transaction_id: UUID
    provider: Literal["stripe", "paystack"]
    client_secret: str | None = None
    authorization_url: str | None = None


class AttestationConsentPendingResponse(BaseModel):
    """Returned for framework requests awaiting framework-owner consent."""

    id: UUID
    status: str


class AttestationConsentRequest(BaseModel):
    """Framework-owner decision on an operator-initiated attestation request."""

    decision: Literal["approve", "decline"]


class AdminCredentialVerifyRequest(BaseModel):
    """Admin request body for verifying a pending Credential.

    Intentionally empty: verification takes no input. The trust decision is
    gated by the step-up window (``require_step_up``) on the route, not by a
    body field.
    """


class AdminCredentialRejectRequest(BaseModel):
    """Admin request body for rejecting a pending Credential."""

    reason: str = Field(min_length=1, max_length=4000)


class AdminCredentialResponse(BaseModel):
    """Credential detail for the admin review queue (includes review evidence)."""

    id: UUID
    user_id: UUID
    title: str
    issuer: str
    issued_date: date
    expires_date: date | None
    credential_type: str | None
    verification_url: str | None
    reference_number: str | None
    issuer_type: str | None
    evidence_file_keys: list[str]
    verification_status: str
    submitted_at: datetime | None
    verified_at: datetime | None
    reviewed_by: UUID | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminCredentialsResponse(BaseModel):
    """Paginated admin credential review queue."""

    credentials: list[AdminCredentialResponse]


class PublicCredentialResponse(BaseModel):
    """Verified Credential fields safe for public profile display.

    Never exposes evidence keys, verification URL, reference number, or review
    metadata — anti-gaming and PII protection.
    """

    title: str
    issuer: str
    credential_type: str | None
    issued_date: date
    expires_date: date | None
    expired: bool


class AttestorDirectoryEntry(BaseModel):
    """Public attestor-organization directory row safe for anonymous browsing.

    Lists the organization's public matching profile, completed-attestation
    count, member count, and certification mark. Never exposes individual member
    identities — attestation is credited to the organization, not its reviewers.
    """

    org_id: UUID
    name: str
    slug: str
    sectors: list[str]
    functions: list[str]
    jurisdictions: list[str]
    verification_level: int
    completed_attestations: int
    member_count: int
    reputation: float | None
    certified: bool = False


class AttestorCompletedAttestation(BaseModel):
    """One public entry in an Attestor's Completed Attestations list."""

    framework_id: UUID
    framework_title: str
    review_type: str
    outcome: Literal["approved", "conditional"]
    issued_at: datetime
    framework_version: str | None


class AttestorDirectoryResponse(BaseModel):
    """Public list response for the Attestor directory."""

    attestors: list[AttestorDirectoryEntry]


class AttestationPackageArtifact(BaseModel):
    """One artifact entry in an Attestation access package."""

    id: UUID
    filename: str | None = None


class AttestationPackageResponse(BaseModel):
    """The read-only Attestation access package scoped to the caller's entitlement."""

    attestation_id: UUID
    framework_title: str
    framework_category: str
    framework_industry: str | None
    # Version of the framework under review, resolved server-side.
    framework_version: str | None = None
    brief: dict[str, Any] | None
    entitlement: str
    artifacts: list[AttestationPackageArtifact]


class AttestationArtifactAccessResponse(BaseModel):
    """Presigned access grant for an Attestation framework artifact."""

    artifact_id: UUID
    attestation_id: UUID
    scope: str
    download_url: str
    expires_in: int


class AttestationRatingCreate(BaseModel):
    """Payload for submitting a rating."""

    stars: int = Field(..., ge=1, le=5, description="1-5 star rating.")
    comment: str | None = Field(
        None, max_length=1000, description="Optional text feedback."
    )


class AttestationRatingResponse(BaseModel):
    """Response showing a saved rating."""

    id: UUID
    attestation_id: UUID
    rated_by: UUID
    stars: int
    comment: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
