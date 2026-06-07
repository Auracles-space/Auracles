"""Pydantic schemas for authenticated settings endpoints."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

from app.core.security import validate_password_strength

KycDocType = Literal[
    "passport",
    "drivers_license",
    "national_id",
    "proof_of_address",
]


class KycUploadUrlRequest(BaseModel):
    """Request body for creating a constrained KYC upload target."""

    doc_type: KycDocType
    mime_type: str
    file_size: int = Field(gt=0)


class KycUploadUrlResponse(BaseModel):
    """Response body for an S3 presigned POST KYC upload target."""

    upload_url: str
    fields: dict[str, str]
    s3_key: str
    max_size: int
    expires_in: int


class KycSubmitRequest(BaseModel):
    """Request body for confirming a KYC object upload."""

    s3_key: str = Field(min_length=1)


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
    """Request body for starting a verified account email change."""

    new_email: EmailStr
    totp_code: str | None = Field(default=None, min_length=6, max_length=16)


class EmailChangeConfirmRequest(BaseModel):
    """Request body for confirming a new account email address."""

    token: str = Field(min_length=1)


class AccountDeactivateRequest(BaseModel):
    """Request body for deactivating the authenticated account."""

    password: SecretStr
    totp_code: str | None = Field(default=None, min_length=6, max_length=16)

    @field_validator("password")
    @classmethod
    def password_has_valid_shape(cls, value: SecretStr) -> SecretStr:
        """Reject impossible passwords before Argon2 verification work."""
        validate_password_strength(value.get_secret_value())
        return value
