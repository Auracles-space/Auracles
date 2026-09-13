"""Pydantic schemas for Organizations Core.

Request and response models in this module cover base organization CRUD,
membership management, and public-safe profile reads.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.core.profile_images import resolve_profile_image_url
from app.modules.attestation.schemas import CoiEntry
from app.modules.library.schemas import LibraryItem
from app.shared.taxonomy import (
    validate_functions,
    validate_jurisdictions,
    validate_sectors,
)

# Block markup delimiters and dangerous control characters, but allow the
# whitespace people type in multi-line textareas: tab (0x09), newline (0x0a),
# and carriage return (0x0d).
_PROSE_FORBIDDEN = re.compile(r"[<>\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
OrgCapabilityName = Literal["contributor", "operator", "attestor"]


def _logo_public_url(logo_key: str | None) -> str | None:
    """Resolve an org ``logo_key`` to a URL its logo can be loaded from.

    The bucket is private, so the URL is signed and short-lived rather than
    derived from the key. Returns ``None`` when the org has no logo.

    Args:
        logo_key: The stored logo object key, or ``None``.

    Returns:
        The public logo URL, or ``None`` when no logo is set.
    """
    return resolve_profile_image_url(logo_key)


def _ensure_safe_prose(value: str) -> str:
    """Reject markup delimiters and control characters in prose fields."""
    if _PROSE_FORBIDDEN.search(value):
        raise ValueError("text may not contain '<', '>', or control characters.")
    return value


def _clean_labels(values: list[str]) -> list[str]:
    """Trim, drop empties, and de-duplicate free-text labels (first-seen)."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = raw.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    return cleaned


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
    # Populated when the org is under a platform suspension, so member-facing
    # surfaces can render a suspension banner. Only ever returned on
    # member-scoped endpoints; the public profile uses a separate schema.
    suspended_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def logo_url(self) -> str | None:
        """Public URL the org logo is served at, or ``None`` when unset."""
        return _logo_public_url(self.logo_key)


class OrgCapabilityResponse(BaseModel):
    """One organization capability row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    capability: str
    status: str
    activated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OrgActionCounts(BaseModel):
    """Per-org counts of items awaiting admin attention.

    Drives the org-card unread dot and the inner-tab count badges. All zero
    for plain members (the tabs these counts feed are admin-only).
    """

    offers: int = 0
    queue: int = 0
    invitations: int = 0


class MyOrganizationResponse(BaseModel):
    """An organization membership visible to the current user."""

    org: OrganizationResponse
    role: str
    capabilities: dict[str, str]
    # Business verification gates every capability, so the shell and the
    # become-attestor entry need it here to route an unverified org to
    # verification rather than into a flow that will refuse it.
    kyb_status: str = "unverified"
    grants: dict[str, bool] = Field(default_factory=dict)
    # True when the org's attestor capability is pending/active, so the
    # frontend can chain invitation acceptance straight into NDA signing.
    nda_required: bool = False
    # Items awaiting admin attention, per org, for badges/dots.
    counts: OrgActionCounts = OrgActionCounts()


class MyOrganizationsResponse(BaseModel):
    """List wrapper for the authenticated user's organizations."""

    organizations: list[MyOrganizationResponse]


class OrganizationUpdateRequest(BaseModel):
    """Partial update of org profile fields (admin+).

    The logo is intentionally NOT settable here: it is set exclusively through
    the verified upload flow (``/logo/upload-url`` + ``/logo/confirm``) so the
    persisted ``logo_key`` always points at an object the org actually uploaded
    into its own namespace, never an arbitrary caller-supplied key.
    """

    name: str | None = Field(default=None, min_length=2, max_length=120)
    website: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name", "website", "description")
    @classmethod
    def strip_optional_value(cls, value: str | None) -> str | None:
        """Trim optional fields while preserving null values."""
        return value.strip() if value is not None else None


class LogoUploadUrlRequest(BaseModel):
    """Declared metadata for an organization logo upload target."""

    mime_type: str = Field(min_length=1, max_length=128)
    file_size: int = Field(gt=0)


class LogoUploadUrlResponse(BaseModel):
    """Presigned POST target for an organization logo upload."""

    upload_url: str
    fields: dict[str, str]
    file_key: str
    max_size: int
    expires_in: int


class LogoConfirmRequest(BaseModel):
    """Confirm a completed organization logo upload by its object key."""

    file_key: str = Field(min_length=1, max_length=512)


class PublicOrganizationResponse(BaseModel):
    """Public org profile: no member identities, no PII."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    logo_key: str | None
    country: str
    website: str | None
    description: str | None
    active_capabilities: list[str]
    member_count: int
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def logo_url(self) -> str | None:
        """Public URL the org logo is served at, or ``None`` when unset."""
        return _logo_public_url(self.logo_key)


class ContributorOrgDirectoryEntry(BaseModel):
    """Public contributor-organization directory row safe for anonymous reads."""

    org_id: UUID
    name: str
    slug: str
    logo_key: str | None
    country: str
    website: str | None
    description: str | None
    verification_level: int
    published_framework_count: int
    member_count: int
    reputation: Decimal | None = Field(default=None, decimal_places=2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def logo_url(self) -> str | None:
        """Public URL the org logo is served at, or ``None`` when unset."""
        return _logo_public_url(self.logo_key)


class ContributorOrgDirectoryResponse(BaseModel):
    """Public list response for contributor organizations."""

    contributors: list[ContributorOrgDirectoryEntry]


class OrgLegalProfileUpdateRequest(BaseModel):
    """Owner-scoped request body for the shared organization legal profile."""

    legal_name: str = Field(min_length=2, max_length=200)
    registration_number: str | None = Field(default=None, min_length=1, max_length=200)
    address: dict[str, Any] | None = None

    @field_validator("legal_name", "registration_number")
    @classmethod
    def _clean_legal_profile_text(cls, value: str | None) -> str | None:
        """Reject markup/control characters in legal-profile text fields."""
        return _ensure_safe_prose(value) if value is not None else None


class OrgLegalProfileResponse(BaseModel):
    """Owner-visible shared legal identity for one organization."""

    org_id: UUID
    legal_name: str
    registration_number: str | None
    address: dict[str, Any] | None
    tax_document_type: str | None
    tax_document_uploaded: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrgPaymentMethodSetupRequest(BaseModel):
    """Request body for starting organization payment-method setup.

    Intentionally empty: the step-up 2FA window is checked by the router
    dependency, so the body carries no fields yet and rejects unknown ones.
    """

    model_config = ConfigDict(extra="forbid")


class OrgPaymentMethodSetupResponse(BaseModel):
    """Stripe SetupIntent data needed to attach an org payment method."""

    provider: Literal["stripe"]
    setup_intent_id: str
    client_secret: str


class OrgPaymentMethodResponse(BaseModel):
    """Safe provider-held payment method metadata returned to org admins."""

    id: str
    provider: Literal["stripe"]
    type: str
    brand: str | None
    last4: str | None
    exp_month: int | None
    exp_year: int | None


class OrgPaymentMethodsResponse(BaseModel):
    """Response body for listing an organization's saved payment methods."""

    payment_methods: list[OrgPaymentMethodResponse]


class OrgPaymentMethodDeleteRequest(BaseModel):
    """Request body for removing a provider-held org payment method.

    Intentionally empty: the step-up 2FA window is checked by the router
    dependency, so the body carries no fields yet and rejects unknown ones.
    """

    model_config = ConfigDict(extra="forbid")


class OrgPaymentMethodDeleteResponse(BaseModel):
    """Response body for a removed organization payment method."""

    provider: Literal["stripe"]
    payment_method_id: str
    removed: bool


class OrgMemberResponse(BaseModel):
    """One organization member, with email hidden from plain members."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    display_name: str
    email: str | None
    role: str
    joined_at: datetime
    # True iff the member holds a current-version platform NDA signature.
    # The trial-nomination picker filters on this. Defaults False so other
    # constructors of this schema stay valid.
    nda_signed: bool = False


class OrgMembersResponse(BaseModel):
    """List wrapper for organization members."""

    members: list[OrgMemberResponse]


class OrgMemberRoleUpdateRequest(BaseModel):
    """Owner-scoped request to switch a member between member and admin."""

    role: Literal["admin", "member"]


class OrgOwnershipTransferRequest(BaseModel):
    """Request to transfer organization ownership (step-up gated at the router)."""

    new_owner_member_id: UUID


class OrgInvitationCreateRequest(BaseModel):
    """Admin-scoped request to invite one email address or existing user."""

    email: EmailStr | None = None
    user_id: UUID | None = None
    role: Literal["admin", "member"]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr | None) -> str | None:
        """Normalize invitation emails to lowercase for unique matching."""
        if value is None:
            return None
        return str(value).strip().lower()

    @model_validator(mode="after")
    def exactly_one_target(self) -> OrgInvitationCreateRequest:
        """Require exactly one invitation target: email or user id."""
        if (self.email is None) == (self.user_id is None):
            raise ValueError("Provide exactly one of email or user_id.")
        return self


class OrgInvitationResponse(BaseModel):
    """One organization invitation row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime


class OrgInvitationsResponse(BaseModel):
    """List wrapper for pending organization invitations."""

    invitations: list[OrgInvitationResponse]


class MemberSearchResult(BaseModel):
    """One masked invite-typeahead suggestion for an organization admin."""

    user_id: UUID
    display_name: str
    avatar_url: str | None
    masked_email: str


class MemberSearchResponse(BaseModel):
    """Capped masked suggestions for the organization invite typeahead."""

    results: list[MemberSearchResult]


class OrgInvitationPreviewResponse(BaseModel):
    """Invitation preview: what the invitee sees before accepting."""

    org_name: str
    org_slug: str
    role: str
    expires_at: datetime


class MyInvitationResponse(BaseModel):
    """A pending invitation addressed to the authenticated user.

    Token-free: the invitee acts on it by id via the received-invitations
    endpoints, never by the raw token.
    """

    id: UUID
    org: OrganizationResponse
    role: str
    invited_by_name: str | None
    created_at: datetime


class MyInvitationsResponse(BaseModel):
    """List wrapper for invitations addressed to the current user."""

    invitations: list[MyInvitationResponse]


class OrgTeamCreateRequest(BaseModel):
    """Admin-scoped request to create a team in an organization."""

    name: str = Field(min_length=2, max_length=80)


class OrgTeamRenameRequest(BaseModel):
    """Admin-scoped request to rename an existing team."""

    name: str = Field(min_length=2, max_length=80)


class OrgTeamResponse(BaseModel):
    """One organization team row with member count and enabled capabilities."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    member_count: int
    capabilities: list[OrgCapabilityName] = Field(default_factory=list)
    created_at: datetime


class OrgTeamMembersResponse(BaseModel):
    """List wrapper for the members belonging to one team."""

    members: list[OrgMemberResponse]


class OrgTeamsResponse(BaseModel):
    """List wrapper for organization teams."""

    teams: list[OrgTeamResponse]


class OrgLicenseGrantRequest(BaseModel):
    """Admin-scoped request to allocate one org License to one target."""

    team_id: UUID | None = None
    member_id: UUID | None = None


class OrgLicenseGrantResponse(BaseModel):
    """One org License grant row exposed to org admins."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    license_id: UUID
    team_id: UUID | None
    member_id: UUID | None
    created_at: datetime


class OrgLicenseGrantsResponse(BaseModel):
    """List wrapper for one org License's allocation rows."""

    grants: list[OrgLicenseGrantResponse]


class OrgLibraryItem(LibraryItem):
    """One org-library item plus its aggregate grant count."""

    grant_count: int


class OrgLibraryResponse(BaseModel):
    """List wrapper for the org shared library visible to one member."""

    items: list[OrgLibraryItem]


class AdminOrgResponse(BaseModel):
    """Platform-admin view of an organization."""

    id: UUID
    slug: str
    name: str
    country: str
    member_count: int
    capabilities: dict[str, str]
    # Business verification gates every capability, so the admin directory
    # reports it alongside them and the queue filters on it.
    kyb_status: str = "unverified"
    legal_name: str | None = None
    registration_number: str | None = None
    kyb_submitted_at: datetime | None = None
    suspended_at: datetime | None = None
    deactivated_at: datetime | None = None
    created_at: datetime


class AdminOrgsResponse(BaseModel):
    """Paginated list of organizations for platform admins."""

    orgs: list[AdminOrgResponse]
    total: int
    page: int
    page_size: int


class OrgNdaStatusResponse(BaseModel):
    """A member's NDA status for one organization.

    Carries the agreement text as well as its version: a member has to be able
    to read what they are signing, and serving it here keeps every signing
    surface on one wording.
    """

    required: bool
    current_version: str
    document: str
    signed_version: str | None = None
    signed_at: datetime | None = None


class OrgAttestorApplicationCreateRequest(BaseModel):
    """Request body to open (or reapply for) an org attestor application.

    KYB fields (legal name, registration number, incorporation documents)
    are optional at draft time and gated for completeness at submit; the
    matching and credentials fields are required so the draft row satisfies
    its NOT NULL columns.
    """

    # No KYB fields: the organization's legal identity is established and
    # verified before it can reach an attestor application at all.
    sectors: list[str] = Field(min_length=1, max_length=12)
    functions: list[str] = Field(min_length=1, max_length=14)
    jurisdictions: list[str] = Field(min_length=1, max_length=24)
    credentials_summary: str = Field(min_length=10, max_length=5000)
    sample_work: dict[str, Any] = Field(default_factory=dict)
    professional_references: str = Field(min_length=3, max_length=5000)

    @field_validator("sectors")
    @classmethod
    def _clean_sectors(cls, value: list[str]) -> list[str]:
        """Validate sectors against the controlled taxonomy."""
        return validate_sectors(value)

    @field_validator("functions")
    @classmethod
    def _clean_functions(cls, value: list[str]) -> list[str]:
        """Validate functions against the canonical framework taxonomy."""
        return validate_functions(value)

    @field_validator("jurisdictions")
    @classmethod
    def _clean_jurisdictions(cls, value: list[str]) -> list[str]:
        """Validate jurisdiction slugs against the canonical set."""
        return validate_jurisdictions(value)

    @field_validator("credentials_summary", "professional_references")
    @classmethod
    def _clean_prose(cls, value: str | None) -> str | None:
        """Reject markup/control characters in prose fields."""
        return _ensure_safe_prose(value) if value is not None else None


class OrgAttestorApplicationUpdateRequest(BaseModel):
    """Partial edit of a draft or needs-info org attestor application.

    Every field is optional: only supplied fields are applied. Setting
    ``payout_account_id`` links an org-owned payout account to the gate.
    """

    # No KYB fields: the organization's legal identity is established and
    # verified before it can reach an attestor application at all.
    sectors: list[str] | None = Field(default=None, min_length=1, max_length=12)
    functions: list[str] | None = Field(default=None, min_length=1, max_length=14)
    jurisdictions: list[str] | None = Field(default=None, min_length=1, max_length=24)
    credentials_summary: str | None = Field(
        default=None, min_length=10, max_length=5000
    )
    sample_work: dict[str, Any] | None = None
    professional_references: str | None = Field(
        default=None, min_length=3, max_length=5000
    )
    payout_account_id: UUID | None = None

    @field_validator("sectors")
    @classmethod
    def _clean_sectors(cls, value: list[str] | None) -> list[str] | None:
        """Validate sectors against the controlled taxonomy when supplied."""
        return validate_sectors(value) if value is not None else None

    @field_validator("functions")
    @classmethod
    def _clean_functions(cls, value: list[str] | None) -> list[str] | None:
        """Validate functions against the taxonomy when supplied."""
        return validate_functions(value) if value is not None else None

    @field_validator("jurisdictions")
    @classmethod
    def _clean_jurisdictions(cls, value: list[str] | None) -> list[str] | None:
        """Validate jurisdiction slugs against the taxonomy when supplied."""
        return validate_jurisdictions(value) if value is not None else None

    @field_validator("credentials_summary", "professional_references")
    @classmethod
    def _clean_prose(cls, value: str | None) -> str | None:
        """Reject markup/control characters in prose fields when supplied."""
        return _ensure_safe_prose(value) if value is not None else None


class OrgUndertakingsSignRequest(BaseModel):
    """Owner-signed conflict-of-interest and confidentiality undertakings.

    Step-up gated at the router: signing stamps the CoI and confidentiality
    timestamps and sets the CoI expiry one validity period out.
    """

    declarations: list[CoiEntry]
    accept_policy: bool
    accept_confidentiality: bool


class OrgAttestorTaxDocumentRequest(BaseModel):
    """Request body to create a presigned tax-document upload session."""

    tax_document_type: Literal["w9", "w8ben", "other"]
    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)


class OrgAttestorIncorporationDocumentRequest(BaseModel):
    """Request body to create a presigned incorporation-document upload session.

    The org uploads incorporation documents (certificate of incorporation and
    similar KYB evidence) to a private bucket; the returned S3 key is appended
    to the organization's ``incorporation_doc_keys`` list server-side.
    """

    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)


class OrgKybStatusResponse(BaseModel):
    """An organization's business-verification state.

    Carries the identity under review alongside the verdict, so one call
    renders the whole verification surface. ``country`` is echoed because the
    document a registration number refers to is country-specific — an RC
    number and CAC certificate in Nigeria, a company number and certificate of
    incorporation elsewhere — and the label belongs with the reader.
    """

    model_config = ConfigDict(from_attributes=True)

    kyb_status: str
    country: str
    legal_name: str | None = None
    registration_number: str | None = None
    incorporation_doc_keys: list[str] = Field(default_factory=list)
    kyb_submitted_at: datetime | None = None
    kyb_verified_at: datetime | None = None
    kyb_review_notes: str | None = None


class OrgKybReviewRequest(BaseModel):
    """Admin verdict on one organization's business verification."""

    verdict: Literal["verified", "rejected"]
    notes: str | None = Field(default=None, max_length=2000)


class OrgAttestorIncorporationDocumentDeleteRequest(BaseModel):
    """Request body to remove one incorporation document from the application."""

    s3_key: str = Field(min_length=1, max_length=1024)


class OrgNominateTrialMemberRequest(BaseModel):
    """Request body to nominate the member who performs the calibration trial."""

    member_id: UUID


class AdminStartTrialRequest(BaseModel):
    """Admin selection of the calibration fixture for a trial."""

    framework_id: UUID


class OrgAttestorGateChecklist(BaseModel):
    """Per-gate readiness flags for an org attestor application.

    Mirrors the admin activation gates so the org can see what remains
    before its application can be approved.
    """

    kyb_verified: bool
    credentials_reviewed: bool
    undertakings_signed: bool
    payout_account_linked: bool
    tax_document_uploaded: bool
    trial_passed: bool


class OrgAttestorApplicationResponse(BaseModel):
    """Org attestor application visible to org owner/admins and platform admins.

    Excludes no confidential reviewing-member identity (there is none on the
    application); the tax document key is an S3 key, not a secret.
    """

    id: UUID
    org_id: UUID
    status: str
    # KYB identity moved to the organization's legal profile; the attestor
    # review reads it from there rather than through this application.
    sectors: list[str]
    functions: list[str]
    jurisdictions: list[str]
    credentials_summary: str
    sample_work: dict[str, Any]
    professional_references: str
    coi_declarations: list[CoiEntry]
    coi_signed_at: datetime | None
    coi_expires_at: datetime | None
    confidentiality_signed_at: datetime | None
    payout_account_id: UUID | None
    tax_document_type: str | None
    tax_document_key: str | None
    trial_member_id: UUID | None
    trial_attestation_id: UUID | None
    admin_feedback: str | None
    reviewed_at: datetime | None
    created_at: datetime
    gate_checklist: OrgAttestorGateChecklist

    model_config = ConfigDict(from_attributes=True)


class TrialRubricDimensionSchema(BaseModel):
    """One rubric dimension the nominee must score for a trial."""

    model_config = ConfigDict(from_attributes=True)

    dimension_id: UUID
    key: str
    label: str
    display_order: int


class TrialArtifactSchema(BaseModel):
    """A calibration-fixture artifact with a short-lived presigned URL."""

    name: str
    mime_type: str
    url: str


class TrialScoreInput(BaseModel):
    """One nominee score submission for a trial dimension."""

    dimension_id: UUID
    score: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=5000)


class TrialSubmitRequest(BaseModel):
    """Full nominee rubric submission for one trial."""

    scores: list[TrialScoreInput] = Field(min_length=1)


class NomineeTrialResponse(BaseModel):
    """The nominated member's live trial workspace view."""

    trial_id: UUID
    status: str
    framework_name: str
    framework_summary: str | None
    artifacts: list[TrialArtifactSchema]
    dimensions: list[TrialRubricDimensionSchema]
    saved_scores: list[TrialScoreInput]
    feedback: str | None


class AdminTrialGradeRow(BaseModel):
    """Per-dimension nominee-vs-key comparison for admin grading."""

    dimension_id: UUID
    label: str
    weight: Decimal
    nominee_score: int | None
    nominee_comment: str | None
    expected_score: int
    tolerance: int


class AdminTrialGradeResponse(BaseModel):
    """Admin trial-grade view with the auto-score suggestion."""

    trial_id: UUID
    status: str
    score_pct: Decimal | None
    auto_result: str | None
    rows: list[AdminTrialGradeRow]


class TrialDecideRequest(BaseModel):
    """Admin confirmation or override of a trial outcome."""

    result: Literal["pass", "fail"]
    feedback: str | None = Field(default=None, max_length=5000)


class CalibrationFixtureItem(BaseModel):
    """One calibration fixture row for the admin trial picker."""

    id: UUID
    title: str
    review_type: str


class CalibrationFixturesResponse(BaseModel):
    """Admin list response for calibration fixtures."""

    fixtures: list[CalibrationFixtureItem]


class CreateCalibrationFixtureRequest(BaseModel):
    """Admin body to create a new calibration fixture shell."""

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=10000)
    review_type: str = Field(min_length=1, max_length=100)


class UpsertTrialAnswerKeyRequest(BaseModel):
    """Admin body to create or update one fixture answer-key row."""

    dimension_id: UUID
    expected_score: int = Field(ge=1, le=5)
    tolerance: int = Field(ge=0, le=4)


class TrialAnswerKeyItem(BaseModel):
    """One answer-key row joined to its rubric dimension, for the admin editor."""

    dimension_id: UUID
    label: str
    expected_score: int | None
    tolerance: int | None


class TrialAnswerKeysResponse(BaseModel):
    """Every rubric dimension for a fixture with its answer-key value, if set."""

    review_type: str
    rows: list[TrialAnswerKeyItem]


class FixtureArtifactUploadUrlRequest(BaseModel):
    """Admin body to create a constrained fixture-artifact upload target."""

    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=150)
    file_size: int = Field(gt=0)


class FixtureArtifactUploadUrlResponse(BaseModel):
    """S3 presigned POST target for one fixture artifact."""

    artifact_id: UUID
    upload_url: str
    fields: dict[str, str]
    file_key: str
    max_size: int
    expires_in: int


class FixtureArtifactConfirmRequest(BaseModel):
    """Admin body confirming a browser-uploaded fixture artifact object."""

    artifact_id: UUID


class FixtureArtifactItem(BaseModel):
    """One fixture artifact with its virus-scan state."""

    id: UUID
    name: str
    mime_type: str
    scan_status: str

    model_config = ConfigDict(from_attributes=True)


class FixtureArtifactsResponse(BaseModel):
    """All artifacts attached to one calibration fixture."""

    artifacts: list[FixtureArtifactItem]


class OrgAttestorAdminListItem(BaseModel):
    """Slim admin-queue row for one org attestor application.

    Omits the heavy content and gate checklist so the queue stays cheap to
    render; admins open the full application for detail.
    """

    id: UUID
    org_id: UUID
    status: str
    # Legal identity and its verdict are read from the organization now and
    # settled on the organization queue; shown here read-only so a reviewer can
    # see who they are approving without leaving the attestor queue.
    org_name: str | None = None
    kyb_status: str | None = None
    reviewed_at: datetime | None
    created_at: datetime
    admin_feedback: str | None
    # Latest calibration-trial state for this application: None if no trial has
    # been assigned, else the enum value (assigned/passed/failed). Lets the
    # admin queue gate Start Trial and Approve in sequence without opening the
    # full application.
    trial_status: str | None = None
    # The org's attestor capability status (pending/active/suspended/revoked),
    # or None if no capability row exists. Lets the admin queue enable only the
    # valid suspend/reinstate/revoke transitions per row.
    capability_status: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OrgAttestorAdminListResponse(BaseModel):
    """Paginated admin queue of org attestor applications."""

    applications: list[OrgAttestorAdminListItem]
    total: int
    page: int
    page_size: int


class OrgAttestorDocumentLink(BaseModel):
    """One presigned download link for an application's review document.

    ``available`` is False when the reserved S3 key has no backing object yet
    (an upload that never completed); the ``url`` is then empty and the admin
    UI shows the document as incomplete rather than a broken link.
    """

    label: str
    filename: str
    url: str
    available: bool = True


class OrgAttestorDocumentsResponse(BaseModel):
    """Presigned GET links for an application's KYB and tax documents.

    Documents live in the private bucket, so the admin panel receives
    short-lived presigned URLs rather than durable paths.
    """

    documents: list[OrgAttestorDocumentLink]


class OrgAttestorFeedbackRequest(BaseModel):
    """Admin feedback body for needs-info and reject actions."""

    feedback: str = Field(min_length=1, max_length=5000)


class OrgAttestationOfferItem(BaseModel):
    """One cohort offer made to an attestor org (owner/admin view)."""

    offer_id: UUID
    attestation_id: UUID
    target_type: str
    target_id: UUID
    # Human-readable name of the offered target (framework title). Null when the
    # target has no resolvable title (e.g. a contributor target).
    target_title: str | None = None
    status: str
    cohort_index: int
    match_score: float | None
    offered_at: datetime
    expires_at: datetime


class OrgAttestationOffersResponse(BaseModel):
    """Open and accepted cohort offers made to an attestor org."""

    offers: list[OrgAttestationOfferItem]


class OrgAcceptOfferRequest(BaseModel):
    """Accept-and-staff body naming the reviewing member for the assignment."""

    reviewing_member_id: UUID


class OrgReassignReviewerRequest(BaseModel):
    """Reassign the reviewing member of an accepted, not-yet-started attestation."""

    reviewing_member_id: UUID


class OrgAttestationItem(BaseModel):
    """One org attestation with internal staffing (owner/admin/member view).

    ``reviewing_member_id`` is org-internal (staffing), never a public or
    requestor-facing field; this schema is only ever returned to org members.
    """

    id: UUID
    target_type: str
    target_id: UUID
    # Human-readable target name (framework title); null for non-framework targets.
    target_title: str | None = None
    review_type: str | None = None
    status: str
    outcome: str | None
    reviewing_member_id: UUID | None
    # Display name of the assigned reviewing member, for a friendly queue view.
    reviewing_member_name: str | None = None
    # True when the requesting caller is the assigned reviewing member, so the
    # workspace can grant write access without knowing internal member ids.
    assigned_to_me: bool = False
    accepted_at: datetime | None
    completion_due_at: datetime | None
    updated_at: datetime | None = None
    # True when the requestor answered a clarification the assigned reviewer has
    # not yet opened, driving the queue card's "answer received" dot.
    unread_answer: bool = False

    model_config = ConfigDict(from_attributes=True)


class OrgAttestationsResponse(BaseModel):
    """An attestor org's attestation queue."""

    attestations: list[OrgAttestationItem]
