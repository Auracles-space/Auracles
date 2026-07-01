"""Pydantic schemas for Attestation and Attestor endpoints."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.attestation.taxonomy import validate_categories, validate_sectors

IssuerType = Literal["institution", "organisation", "government", "association"]

# Safe charset for short controlled labels (specializations, jurisdictions):
# letters, digits, spaces, and a few separators. Excludes ``;``, angle brackets,
# quotes, and other punctuation that signals injected or malformed input.
_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,&/()\-]*$")
# Characters never allowed in free-text prose: markup delimiters and ASCII
# control characters (tab/newline excepted) that have no place in plain text.
_PROSE_FORBIDDEN = re.compile(r"[<>\x00-\x08\x0b\x0c\x0e-\x1f]")
_CREDENTIAL_ISSUING_BODIES = frozenset(
    {
        "cfa_institute",
        "aicpa",
        "isaca",
        "rics",
        "sra",
        "state_bar",
        "fca",
        "acams",
        "other",
    }
)


def _normalise_labels(values: list[str]) -> list[str]:
    """Trim, validate, and de-duplicate a list of short controlled labels.

    Each item is stripped and must match the safe label charset. Duplicates are
    removed case-insensitively while preserving first-seen order.

    Args:
        values: Raw label strings from the request body.

    Returns:
        The cleaned, de-duplicated labels.

    Raises:
        ValueError: If an item is empty or contains disallowed characters.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = raw.strip()
        if not item:
            raise ValueError("items cannot be empty.")
        if not _LABEL_PATTERN.match(item):
            raise ValueError(
                "items may only contain letters, numbers, spaces, and . , & / ( ) -"
            )
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    if not cleaned:
        raise ValueError("at least one item is required.")
    return cleaned


def _ensure_safe_prose(value: str) -> str:
    """Reject free-text prose containing markup or control characters.

    Args:
        value: Raw prose value from the request body.

    Returns:
        The original value when it contains only safe characters.

    Raises:
        ValueError: If the value contains markup delimiters or control chars.
    """
    if _PROSE_FORBIDDEN.search(value):
        raise ValueError("text may not contain '<', '>', or control characters.")
    return value


class _AttestorApplicationFields(BaseModel):
    """Shared, sanitized fields for submitting and editing applications.

    Centralizes the input-hardening rules so create and edit accept identical,
    cleaned data: controlled labels are trimmed/de-duplicated against a safe
    charset or a controlled taxonomy, and prose fields reject markup and
    control characters.
    """

    legal_name: str = Field(min_length=2, max_length=200)
    linkedin_url: str | None = Field(default=None, max_length=2048)
    professional_body_numbers: dict[str, str] = Field(default_factory=dict)
    sectors: list[str] = Field(min_length=1, max_length=4)
    framework_categories: list[str] = Field(min_length=1, max_length=9)
    jurisdictions: list[str] = Field(min_length=1, max_length=25)
    credentials_summary: str = Field(min_length=10, max_length=5000)
    sample_work: dict[str, Any] = Field(default_factory=dict)
    professional_references: str = Field(min_length=3, max_length=5000)

    @field_validator("sectors")
    @classmethod
    def _clean_sectors(cls, value: list[str]) -> list[str]:
        """Validate sectors against the controlled taxonomy."""
        return validate_sectors(value)

    @field_validator("framework_categories")
    @classmethod
    def _clean_categories(cls, value: list[str]) -> list[str]:
        """Validate framework categories against the controlled taxonomy."""
        return validate_categories(value)

    @field_validator("jurisdictions")
    @classmethod
    def _clean_jurisdictions(cls, value: list[str]) -> list[str]:
        """Trim/validate jurisdiction labels."""
        return _normalise_labels(value)

    @field_validator("legal_name", "credentials_summary", "professional_references")
    @classmethod
    def _clean_prose(cls, value: str) -> str:
        """Reject markup/control characters in prose fields."""
        return _ensure_safe_prose(value)


class AttestorApplicationCreateRequest(_AttestorApplicationFields):
    """Request body for submitting an Attestor role application."""


class AttestorApplicationUpdateRequest(_AttestorApplicationFields):
    """Request body for editing a pending Attestor application in place."""


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


class CoiDeclarationRequest(BaseModel):
    """Request body for signing the Attestor conflict-of-interest declaration."""

    declarations: list[CoiEntry]
    accept_policy: bool


class ConfidentialityAgreementRequest(BaseModel):
    """Attestor acceptance of the one-time confidentiality / non-use agreement."""

    accept: bool


class AttestorPayoutAttachRequest(BaseModel):
    """Request body for attaching an owned payout account to the application."""

    payout_account_id: UUID


class AttestorTaxDocumentRequest(BaseModel):
    """Request body for creating an Attestor tax-document upload session."""

    tax_document_type: Literal["w9", "w8ben", "other"]
    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)


class AttestorApplicationResponse(BaseModel):
    """Attestor application details visible to its owner and admins."""

    id: UUID
    user_id: UUID
    status: str
    legal_name: str | None
    linkedin_url: str | None
    professional_body_numbers: dict[str, str]
    sectors: list[str]
    framework_categories: list[str]
    needs_retag: bool
    jurisdictions: list[str]
    credentials_summary: str
    sample_work: dict[str, Any]
    professional_references: str
    coi_declarations: list[CoiEntry]
    coi_signed_at: datetime | None
    confidentiality_signed_at: datetime | None
    coi_expires_at: datetime | None
    payout_account_id: UUID | None
    tax_document_type: str | None
    tax_document_key: str | None
    admin_feedback: str | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AttestorApplicationsResponse(BaseModel):
    """List response for Attestor applications."""

    applications: list[AttestorApplicationResponse]


class AttestorApplicationRejectRequest(BaseModel):
    """Admin request body for rejecting an Attestor application."""

    feedback: str = Field(min_length=1, max_length=5000)
    totp_code: str = Field(min_length=6, max_length=16)


class AttestorKycVerifyRequest(BaseModel):
    """Admin request body for the KYC verification onboarding gate."""

    name_match: bool
    totp_code: str = Field(min_length=6, max_length=16)


class AttestorCredentialCheckRequest(BaseModel):
    """Admin request body for the credential registry cross-check gate."""

    credential_id: UUID
    issuing_body: str
    good_standing: bool
    registry_reference: str
    totp_code: str = Field(min_length=6, max_length=16)

    @field_validator("issuing_body")
    @classmethod
    def _validate_issuing_body(cls, value: str) -> str:
        """Accept only controlled credential-body enum values."""
        if value not in _CREDENTIAL_ISSUING_BODIES:
            raise ValueError(f"{value!r} is not a valid credential issuing body.")
        return value


class AttestorTrialAssignRequest(BaseModel):
    """Admin request body for assigning a stubbed calibration trial."""

    seeded_framework_id: UUID | None = None
    totp_code: str = Field(min_length=6, max_length=16)


class AttestorTrialDecideRequest(BaseModel):
    """Admin request body for deciding a stubbed calibration trial."""

    passed: bool
    feedback: str | None = None
    totp_code: str = Field(min_length=6, max_length=16)


class AttestorActivateRequest(BaseModel):
    """Admin request body for activating a fully verified Attestor."""

    totp_code: str = Field(min_length=6, max_length=16)


class AttestorTrialResponse(BaseModel):
    """Calibration trial details returned to admins."""

    id: UUID
    application_id: UUID
    seeded_framework_id: UUID | None
    status: str
    attempt: int

    model_config = ConfigDict(from_attributes=True)


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
    summary: str = Field(min_length=20, max_length=10000)
    scope: str = Field(min_length=10, max_length=10000)
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
    resolution_type: str | None
    release_amount: Decimal | None
    refund_amount: Decimal | None
    admin_id: UUID | None
    resolution_notes: str | None
    escalated_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminAttestationDisputeResolveRequest(BaseModel):
    """Admin request body for resolving an Attestation dispute."""

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


class AdminAttestationAssignRequest(BaseModel):
    """Admin request body for manually assigning a needs-admin Attestation."""

    attestor_id: UUID
    reason: str = Field(min_length=5, max_length=4000)
    totp_code: str = Field(min_length=6, max_length=16)


class AdminAttestationRefundRequest(BaseModel):
    """Admin request body for refunding a needs-admin Attestation."""

    reason: str = Field(min_length=5, max_length=4000)
    totp_code: str = Field(min_length=6, max_length=16)


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
    requested_specializations: list[str] = Field(min_length=1, max_length=25)
    requested_jurisdictions: list[str] = Field(min_length=1, max_length=25)


class AttestationRequestResponse(BaseModel):
    """Attestation request details visible to requestor and assigned Attestor."""

    id: UUID
    target_type: str
    target_id: UUID
    requestor_id: UUID
    attestor_id: UUID | None
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

    model_config = ConfigDict(from_attributes=True)


class AttestationsResponse(BaseModel):
    """List response for Attestations visible to the authenticated user."""

    attestations: list[AttestationRequestResponse]


class AttestorAssignmentResponse(BaseModel):
    """Attestation offer or assignment visible to an approved Attestor."""

    offer_id: UUID
    attestation_id: UUID
    target_type: str
    target_id: UUID
    attestation_status: str
    offer_status: str
    cohort_index: int
    requestor_id: UUID
    requestor_flagged: bool
    requested_specializations: list[str]
    requested_jurisdictions: list[str]
    expires_at: datetime
    accepted_at: datetime | None
    completion_due_at: datetime | None


class AttestorAssignmentsResponse(BaseModel):
    """List response for an Attestor's open offers and accepted work."""

    assignments: list[AttestorAssignmentResponse]


class AttestationFundingResponse(BaseModel):
    """PaymentIntent data needed to fund an Attestation fee escrow."""

    id: UUID
    transaction_id: UUID
    provider: Literal["stripe"]
    client_secret: str


class AttestationConsentPendingResponse(BaseModel):
    """Returned for framework requests awaiting framework-owner consent."""

    id: UUID
    status: str


class AttestationConsentRequest(BaseModel):
    """Framework-owner decision on an operator-initiated attestation request."""

    decision: Literal["approve", "decline"]


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
    """Public Attestor directory row safe for anonymous browsing."""

    user_id: UUID
    display_name: str
    sectors: list[str]
    framework_categories: list[str]
    jurisdictions: list[str]
    verification_level: int
    credentials: list[PublicCredentialResponse]
    completed_attestations: int
    reputation: float | None


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

    model_config = ConfigDict(from_attributes=True)
