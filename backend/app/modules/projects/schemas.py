"""Pydantic schemas for Project and Proposal endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DeliverableSpec(BaseModel):
    """Small deliverable description embedded in Project and Proposal payloads."""

    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)


class ProjectCreateRequest(BaseModel):
    """Operator request body for creating a Project."""

    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=10, max_length=10000)
    category: str = Field(min_length=1, max_length=100)
    required_deliverables: list[DeliverableSpec] = Field(min_length=1)
    budget_min: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    budget_max: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    deadline: date | None = None

    @field_validator("currency")
    @classmethod
    def currency_must_be_usd(cls, value: str) -> str:
        """Reject non-USD Project creation during the MVP currency lock."""
        if value.upper() != "USD":
            raise ValueError("Project currency must be USD.")
        return value.upper()

    @field_validator("budget_max")
    @classmethod
    def budget_range_is_ordered(cls, value: Decimal, info: Any) -> Decimal:
        """Ensure max budget is not lower than min budget."""
        budget_min = info.data.get("budget_min")
        if budget_min is not None and value < budget_min:
            raise ValueError("budget_max must be greater than or equal to budget_min.")
        return value


class ProjectUpdateRequest(BaseModel):
    """Operator request body for editing an open Project."""

    title: str | None = Field(default=None, min_length=3, max_length=255)
    description: str | None = Field(default=None, min_length=10, max_length=10000)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    required_deliverables: list[DeliverableSpec] | None = Field(
        default=None,
        min_length=1,
    )
    budget_min: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
    )
    budget_max: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
    )
    deadline: date | None = None


class ProposalCreateRequest(BaseModel):
    """Contributor request body for submitting a Proposal."""

    scope: str = Field(min_length=10, max_length=10000)
    budget: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    timeline_days: int = Field(gt=0, le=3650)
    deliverables: list[DeliverableSpec] = Field(min_length=1)

    @field_validator("currency")
    @classmethod
    def currency_must_be_usd(cls, value: str) -> str:
        """Reject non-USD Proposal submission during the MVP currency lock."""
        if value.upper() != "USD":
            raise ValueError("Proposal currency must be USD.")
        return value.upper()


class ProjectResponse(BaseModel):
    """Project response returned by CRUD and assignment endpoints."""

    id: UUID
    operator_id: UUID
    title: str
    description: str
    category: str
    required_deliverables: list[dict[str, Any]]
    budget_min: Decimal
    budget_max: Decimal
    currency: str
    deadline: date | None
    status: str
    milestone_plan_status: str
    expires_at: datetime
    accepted_proposal_id: UUID | None
    delivered_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectsResponse(BaseModel):
    """Paginated Project list response."""

    projects: list[ProjectResponse]
    total: int
    page: int
    page_size: int


class ProposalResponse(BaseModel):
    """Proposal response returned to authors and Project owners."""

    id: UUID
    project_id: UUID
    contributor_id: UUID
    scope: str
    budget: Decimal
    currency: str
    timeline_days: int
    deliverables: list[dict[str, Any]]
    status: str
    withdrawn_at: datetime | None
    accepted_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProposalsResponse(BaseModel):
    """List response for Project proposals."""

    proposals: list[ProposalResponse]
