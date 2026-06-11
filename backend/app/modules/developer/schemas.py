"""Pydantic schemas for Developer platform endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class DeveloperApplicationCreateRequest(BaseModel):
    """Request body for submitting a Developer role application."""

    company_name: str = Field(min_length=2, max_length=255)
    website: HttpUrl | None = None
    use_case: str = Field(min_length=20, max_length=5000)


class DeveloperApplicationResponse(BaseModel):
    """Developer application details visible to its owner and admins."""

    id: UUID
    user_id: UUID
    company_name: str
    website: str | None
    use_case: str
    status: str
    admin_feedback: str | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeveloperApplicationsResponse(BaseModel):
    """List response for Developer applications."""

    applications: list[DeveloperApplicationResponse]


class DeveloperApplicationReviewRequest(BaseModel):
    """Admin request body for approving or rejecting a Developer application."""

    decision: Literal["approved", "rejected"]
    feedback: str | None = Field(default=None, max_length=5000)
    totp_code: str = Field(min_length=6, max_length=16)
