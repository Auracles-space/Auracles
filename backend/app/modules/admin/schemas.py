"""Pydantic schemas for admin endpoints."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AdminRoleAssignmentRequest(BaseModel):
    """Request body for assigning or approving a user role."""

    role: Literal["contributor", "operator", "attestor", "admin"]


class AdminRoleAssignmentResponse(BaseModel):
    """Response body for admin role assignment."""

    user_id: UUID
    role: str
    approved: bool


class AdminKycReviewRequest(BaseModel):
    """Request body for admin KYC review decisions."""

    status: Literal["verified", "rejected"]
    notes: str | None = None


class AdminKycReviewResponse(BaseModel):
    """Response body for admin KYC review."""

    user_id: UUID
    kyc_status: str
    document_status: str


class AdminFrameworkSuspendRequest(BaseModel):
    """Request body for post-publish Framework suspension."""

    reason: str = Field(min_length=1)


class AdminFrameworkStatusResponse(BaseModel):
    """Response body for admin Framework state changes."""

    framework_id: UUID
    status: str
    reason: str | None = None


class AdminLicenseGrantRequest(BaseModel):
    """Request body for admin-mediated license grants."""

    framework_id: UUID
    operator_id: UUID
    type: Literal["single_user", "team", "enterprise"]
    expires_at: datetime | None = None
    seats_total: int | None = Field(default=None, ge=1)


class AdminLicenseGrantResponse(BaseModel):
    """Response body for an admin-created license."""

    license_id: UUID
    framework_id: UUID
    operator_id: UUID
    type: str
    status: str
    version_at_grant: str
    seats_used: int
    seats_total: int | None
    expires_at: datetime | None
