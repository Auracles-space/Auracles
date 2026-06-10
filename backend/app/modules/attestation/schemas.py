"""Pydantic schemas for Attestation and Attestor endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AttestorApplicationCreateRequest(BaseModel):
    """Request body for submitting an Attestor role application."""

    specializations: list[str] = Field(min_length=1, max_length=25)
    jurisdictions: list[str] = Field(min_length=1, max_length=25)
    credentials_summary: str = Field(min_length=10, max_length=5000)
    sample_work: dict[str, Any] = Field(default_factory=dict)
    professional_references: str = Field(min_length=3, max_length=5000)


class AttestorApplicationResponse(BaseModel):
    """Attestor application details visible to its owner and admins."""

    id: UUID
    user_id: UUID
    status: str
    specializations: list[str]
    jurisdictions: list[str]
    credentials_summary: str
    sample_work: dict[str, Any]
    professional_references: str
    admin_feedback: str | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AttestorApplicationsResponse(BaseModel):
    """List response for Attestor applications."""

    applications: list[AttestorApplicationResponse]


class AttestorApplicationReviewRequest(BaseModel):
    """Admin request body for approving or rejecting an Attestor application."""

    decision: Literal["approved", "rejected"]
    feedback: str | None = Field(default=None, max_length=5000)
    totp_code: str = Field(min_length=6, max_length=16)


class CredentialCreateRequest(BaseModel):
    """Request body for creating a user-owned Credential."""

    title: str = Field(min_length=1, max_length=255)
    issuer: str = Field(min_length=1, max_length=255)
    issued_date: date
    expires_date: date | None = None

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
    evidence_references: dict[str, Any] = Field(default_factory=dict)


class AttestationRequestCreateRequest(BaseModel):
    """Request body for creating an escrow-funded Attestation request."""

    target_type: Literal["framework", "contributor", "operator", "credential"]
    target_id: UUID
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


class AttestorAssignmentResponse(BaseModel):
    """Attestation offer or assignment visible to an approved Attestor."""

    offer_id: UUID
    attestation_id: UUID
    target_type: str
    target_id: UUID
    attestation_status: str
    offer_status: str
    cohort_index: int
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
