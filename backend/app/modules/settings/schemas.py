"""Pydantic schemas for authenticated settings endpoints."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

KycDocType = Literal[
    "passport",
    "drivers_license",
    "national_id",
    "proof_of_address",
]


class KycUploadUrlRequest(BaseModel):
    """Request body for creating a constrained KYC upload URL."""

    doc_type: KycDocType
    mime_type: str
    file_size: int = Field(gt=0)


class KycUploadUrlResponse(BaseModel):
    """Response body for a presigned KYC upload URL."""

    upload_url: str
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
