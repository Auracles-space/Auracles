"""Pydantic schemas for GDPR and data-rights endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


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
