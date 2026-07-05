"""Pydantic schemas for Organizations Core.

Request and response models in this module cover base organization CRUD,
membership management, and public-safe profile reads.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.attestation.schemas import CoiEntry
from app.modules.attestation.taxonomy import validate_categories, validate_sectors

_PROSE_FORBIDDEN = re.compile(r"[<>\x00-\x1f\x7f]")


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


class MyOrganizationResponse(BaseModel):
    """An organization membership visible to the current user."""

    org: OrganizationResponse
    role: str
    capabilities: dict[str, str]
    # True when the org's attestor capability is pending/active, so the
    # frontend can chain invitation acceptance straight into NDA signing.
    nda_required: bool = False


class MyOrganizationsResponse(BaseModel):
    """List wrapper for the authenticated user's organizations."""

    organizations: list[MyOrganizationResponse]


class OrganizationUpdateRequest(BaseModel):
    """Partial update of org profile fields (admin+)."""

    name: str | None = Field(default=None, min_length=2, max_length=120)
    website: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    logo_key: str | None = Field(default=None, max_length=512)

    @field_validator("name", "website", "description", "logo_key")
    @classmethod
    def strip_optional_value(cls, value: str | None) -> str | None:
        """Trim optional fields while preserving null values."""
        return value.strip() if value is not None else None


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


class OrgMemberResponse(BaseModel):
    """One organization member, with email hidden from plain members."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    display_name: str
    email: str | None
    role: str
    joined_at: datetime


class OrgMembersResponse(BaseModel):
    """List wrapper for organization members."""

    members: list[OrgMemberResponse]


class OrgMemberRoleUpdateRequest(BaseModel):
    """Owner-scoped request to switch a member between member and admin."""

    role: Literal["admin", "member"]


class OrgOwnershipTransferRequest(BaseModel):
    """TOTP-gated request to transfer organization ownership."""

    new_owner_member_id: UUID
    totp_code: str = Field(min_length=6, max_length=16)


class OrgInvitationCreateRequest(BaseModel):
    """Admin-scoped request to invite one email address into an organization."""

    email: EmailStr
    role: Literal["admin", "member"]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        """Normalize invitation emails to lowercase for unique matching."""
        return str(value).strip().lower()


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


class OrgInvitationPreviewResponse(BaseModel):
    """Invitation preview: what the invitee sees before accepting."""

    org_name: str
    org_slug: str
    role: str
    expires_at: datetime


class OrgTeamCreateRequest(BaseModel):
    """Admin-scoped request to create a team in an organization."""

    name: str = Field(min_length=2, max_length=80)


class OrgTeamRenameRequest(BaseModel):
    """Admin-scoped request to rename an existing team."""

    name: str = Field(min_length=2, max_length=80)


class OrgTeamResponse(BaseModel):
    """One organization team row with member count."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    member_count: int
    created_at: datetime


class OrgTeamsResponse(BaseModel):
    """List wrapper for organization teams."""

    teams: list[OrgTeamResponse]


class AdminOrgResponse(BaseModel):
    """Platform-admin view of an organization."""

    id: UUID
    slug: str
    name: str
    country: str
    member_count: int
    capabilities: dict[str, str]
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
    """A member's NDA status for one organization."""

    required: bool
    current_version: str
    signed_version: str | None = None
    signed_at: datetime | None = None


class OrgAttestorApplicationCreateRequest(BaseModel):
    """Request body to open (or reapply for) an org attestor application.

    KYB fields (legal name, registration number, incorporation documents)
    are optional at draft time and gated for completeness at submit; the
    matching and credentials fields are required so the draft row satisfies
    its NOT NULL columns.
    """

    legal_name: str | None = Field(default=None, min_length=2, max_length=200)
    registration_number: str | None = Field(default=None, min_length=1, max_length=200)
    incorporation_doc_keys: list[str] = Field(default_factory=list, max_length=20)
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
        """Trim and de-duplicate jurisdiction labels."""
        return _clean_labels(value)

    @field_validator("legal_name", "credentials_summary", "professional_references")
    @classmethod
    def _clean_prose(cls, value: str | None) -> str | None:
        """Reject markup/control characters in prose fields."""
        return _ensure_safe_prose(value) if value is not None else None


class OrgAttestorApplicationUpdateRequest(BaseModel):
    """Partial edit of a draft or needs-info org attestor application.

    Every field is optional: only supplied fields are applied. Setting
    ``payout_account_id`` links an org-owned payout account to the gate.
    """

    legal_name: str | None = Field(default=None, min_length=2, max_length=200)
    registration_number: str | None = Field(default=None, min_length=1, max_length=200)
    incorporation_doc_keys: list[str] | None = Field(default=None, max_length=20)
    sectors: list[str] | None = Field(default=None, min_length=1, max_length=4)
    framework_categories: list[str] | None = Field(
        default=None, min_length=1, max_length=9
    )
    jurisdictions: list[str] | None = Field(default=None, min_length=1, max_length=25)
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

    @field_validator("framework_categories")
    @classmethod
    def _clean_categories(cls, value: list[str] | None) -> list[str] | None:
        """Validate framework categories against the taxonomy when supplied."""
        return validate_categories(value) if value is not None else None

    @field_validator("jurisdictions")
    @classmethod
    def _clean_jurisdictions(cls, value: list[str] | None) -> list[str] | None:
        """Trim and de-duplicate jurisdiction labels when supplied."""
        return _clean_labels(value) if value is not None else None

    @field_validator("legal_name", "credentials_summary", "professional_references")
    @classmethod
    def _clean_prose(cls, value: str | None) -> str | None:
        """Reject markup/control characters in prose fields when supplied."""
        return _ensure_safe_prose(value) if value is not None else None


class OrgUndertakingsSignRequest(BaseModel):
    """Owner-signed conflict-of-interest and confidentiality undertakings.

    TOTP-gated: signing stamps the CoI and confidentiality timestamps and
    sets the CoI expiry one validity period out.
    """

    declarations: list[CoiEntry]
    accept_policy: bool
    accept_confidentiality: bool
    totp_code: str = Field(min_length=6, max_length=16)


class OrgAttestorTaxDocumentRequest(BaseModel):
    """Request body to create a presigned tax-document upload session."""

    tax_document_type: Literal["w9", "w8ben", "other"]
    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)


class OrgNominateTrialMemberRequest(BaseModel):
    """Request body to nominate the member who performs the calibration trial."""

    member_id: UUID


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
    legal_name: str | None
    registration_number: str | None
    incorporation_doc_keys: list[str]
    sectors: list[str]
    framework_categories: list[str]
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
    kyb_verified_at: datetime | None
    admin_feedback: str | None
    reviewed_at: datetime | None
    created_at: datetime
    gate_checklist: OrgAttestorGateChecklist

    model_config = ConfigDict(from_attributes=True)
