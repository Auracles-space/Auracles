"""Pydantic schemas for Attestation and Attestor endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
