"""Pydantic schemas for authenticated settings endpoints."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


class KycDocumentResponse(BaseModel):
    """Public KYC document metadata returned to the document owner.

    Deliberately omits ``s3_key``. Identity documents are delivered by presigned
    URL only, and publishing the object key would hand out a target list that
    outlives any single presigned link.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    doc_type: str
    mime_type: str
    file_size: int
    status: str
    scan_status: str
    reviewed_at: datetime | None
    notes: str | None
    created_at: datetime


class KycStatusResponse(BaseModel):
    """Authenticated user's KYC status and document metadata."""

    kyc_status: str
    documents: list[KycDocumentResponse]


class KycDocumentUploadRequest(BaseModel):
    """Request for a presigned target to upload one identity document.

    ``file_size`` is declared up front so an oversized file is refused before a
    single byte reaches S3; the presigned policy then enforces the same ceiling
    server-side, so a client that lies about it still cannot exceed the cap.
    """

    doc_type: Literal["passport", "drivers_license", "national_id", "proof_of_address"]
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=100)
    file_size: int = Field(gt=0)


class KycDocumentUploadResponse(BaseModel):
    """Presigned POST target for one identity document upload.

    The client posts a multipart form to ``upload_url`` containing every entry
    in ``fields`` followed by the file part, then calls the confirm endpoint
    with ``document_id``.
    """

    document_id: UUID
    upload_url: str
    fields: dict[str, str]
    max_size: int
    expires_in: int


class KycVerificationSessionResponse(BaseModel):
    """Hosted Persona verification link for the authenticated user.

    The frontend redirects the user to ``hosted_url`` to complete identity
    verification; the Persona webhook later flips ``kyc_status``.

    ``inquiry_id`` is null on issue. The link is a hosted flow, so Persona mints
    the inquiry only when the user arrives — the id first reaches us on the
    return redirect (as ``inquiry-id``) or on the webhook. Clients must not
    depend on it being present here.
    """

    hosted_url: str
    inquiry_id: str | None = None


class KycSyncRequest(BaseModel):
    """Request to reconcile KYC state from a returned Persona inquiry.

    Sent when the user lands back from the hosted flow. ``inquiry_id`` is the
    ``inquiry-id`` Persona appends to the return URL; the backend reads that
    inquiry's authoritative verdict and applies it (ownership-checked).
    """

    inquiry_id: str = Field(min_length=1, max_length=128)


class SessionResponse(BaseModel):
    """Public metadata for one active refresh-token session."""

    id: str
    ip: str | None
    user_agent: str | None
    last_seen: datetime
    created_at: datetime
    current: bool


class SessionsResponse(BaseModel):
    """Response body for active browser sessions."""

    sessions: list[SessionResponse]


class EmailChangeRequest(BaseModel):
    """Request body for starting a verified account email change.

    Password accounts re-authenticate with the account password and, when 2FA is
    enabled, step up with a TOTP/backup code. Passwordless (e.g. Google) accounts
    omit the password; the new-address verification link is the proof of intent
    and TOTP still applies when enabled.
    """

    new_email: EmailStr
    password: SecretStr | None = None
    totp_code: str | None = Field(default=None, min_length=6, max_length=16)


class EmailChangeConfirmRequest(BaseModel):
    """Request body for confirming a new account email address."""

    token: str = Field(min_length=1)
