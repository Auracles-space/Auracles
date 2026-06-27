"""Pydantic schemas for GDPR and data-rights endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr


class ConsentAcceptRequest(BaseModel):
    """Request body for accepting the current legal document versions."""

    accept_terms: Literal[True]
    accept_privacy_policy: Literal[True]


class ConsentLogItem(BaseModel):
    """Single consent log entry returned to the owning user."""

    id: UUID
    document_type: str
    version: str
    accepted_at: datetime


class ConsentHistoryResponse(BaseModel):
    """Consent status and append-only history for the current user."""

    current_versions: dict[str, str]
    missing_documents: list[str]
    items: list[ConsentLogItem]


class DataExportRequestResponse(BaseModel):
    """Status response for a GDPR data export request."""

    id: UUID
    status: str
    requested_at: datetime
    completed_at: datetime | None
    expires_at: datetime | None
    failure_reason: str | None


class AccountDeletionRequestBody(BaseModel):
    """Request body for starting the GDPR account-deletion cooling-off flow.

    Password accounts confirm with their password; passwordless (e.g. Google)
    accounts omit it and rely on the deletion grace period as the safety net.
    TOTP still applies when the account has it enabled.
    """

    password: SecretStr | None = None
    totp_code: str | None = Field(default=None, min_length=6, max_length=16)


class AccountDeletionBlockedReason(BaseModel):
    """One reason why GDPR account deletion is currently blocked."""

    code: str
    message: str
    count: int | None = None


class AccountDeletionStatusResponse(BaseModel):
    """Latest GDPR account-deletion request state for the current user."""

    id: UUID | None
    status: str | None
    blocked_reasons: list[AccountDeletionBlockedReason]
    scheduled_for: datetime | None
    requested_at: datetime | None
    completed_at: datetime | None
