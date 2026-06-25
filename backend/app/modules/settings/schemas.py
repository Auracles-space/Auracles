"""Pydantic schemas for authenticated settings endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


class KycDocumentResponse(BaseModel):
    """Public KYC document metadata returned to the document owner."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    doc_type: str
    s3_key: str
    mime_type: str
    file_size: int
    status: str
    reviewed_at: datetime | None
    notes: str | None
    created_at: datetime


class KycStatusResponse(BaseModel):
    """Authenticated user's KYC status and document metadata."""

    kyc_status: str
    documents: list[KycDocumentResponse]


class KycVerificationSessionResponse(BaseModel):
    """Hosted Persona verification link for the authenticated user.

    The frontend redirects the user to ``hosted_url`` to complete identity
    verification; the Persona webhook later flips ``kyc_status``.
    """

    hosted_url: str
    inquiry_id: str


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

    Email change always re-authenticates with the account password and, when the
    account has 2FA enabled, additionally steps up with a TOTP/backup code.
    """

    new_email: EmailStr
    password: SecretStr
    totp_code: str | None = Field(default=None, min_length=6, max_length=16)


class EmailChangeConfirmRequest(BaseModel):
    """Request body for confirming a new account email address."""

    token: str = Field(min_length=1)
