"""Pydantic schemas for admin endpoints."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class AdminRoleAssignmentRequest(BaseModel):
    """Request body for assigning or approving a user role."""

    role: Literal["contributor", "operator", "attestor", "admin"]


class AdminRoleAssignmentResponse(BaseModel):
    """Response body for admin role assignment."""

    user_id: UUID
    role: str
    approved: bool
