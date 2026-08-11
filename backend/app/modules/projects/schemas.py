"""Pydantic schemas for Project and Proposal endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.currency import normalize_platform_currency, platform_currency
from app.modules.reputation.schemas import ReputationSummary


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
    currency: str = Field(
        default_factory=platform_currency,
        min_length=3,
        max_length=3,
    )
    deadline: date | None = None

    @field_validator("currency")
    @classmethod
    def currency_is_the_platform_currency(cls, value: str) -> str:
        """Pin Project amounts to the platform's settlement currency."""
        return normalize_platform_currency(value)

    @field_validator("budget_max")
    @classmethod
    def budget_range_is_ordered(cls, value: Decimal, info: Any) -> Decimal:
        """Ensure max budget is not lower than min budget."""
        budget_min = info.data.get("budget_min")
        if budget_min is not None and value < budget_min:
            raise ValueError("budget_max must be greater than or equal to budget_min.")
        return value

    @field_validator("deadline")
    @classmethod
    def deadline_cannot_be_in_the_past(cls, value: date | None) -> date | None:
        """Reject Project deadlines earlier than today."""
        if value is not None and value < date.today():
            raise ValueError("deadline cannot be in the past.")
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

    @field_validator("deadline")
    @classmethod
    def deadline_cannot_be_in_the_past(cls, value: date | None) -> date | None:
        """Reject Project deadline edits that move the date into the past."""
        if value is not None and value < date.today():
            raise ValueError("deadline cannot be in the past.")
        return value


class ProposalCreateRequest(BaseModel):
    """Contributor request body for submitting a Proposal."""

    scope: str = Field(min_length=10, max_length=10000)
    budget: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(
        default_factory=platform_currency,
        min_length=3,
        max_length=3,
    )
    timeline_days: int = Field(gt=0, le=3650)
    deliverables: list[DeliverableSpec] = Field(min_length=1)

    @field_validator("currency")
    @classmethod
    def currency_is_the_platform_currency(cls, value: str) -> str:
        """Pin Proposal amounts to the platform's settlement currency."""
        return normalize_platform_currency(value)


class OrgProposalCreateRequest(ProposalCreateRequest):
    """Organization-admin request body for submitting an org Proposal."""

    delivering_member_id: UUID


class OrgProposalReassignRequest(BaseModel):
    """Organization-admin request body for reassigning staffed delivery."""

    delivering_member_id: UUID


class AmendmentCreateRequest(BaseModel):
    """Project member request body for proposing a Proposal amendment."""

    change_type: Literal["scope", "budget", "timeline", "combo"]
    after: dict[str, Any]
    reason: str = Field(min_length=5, max_length=4000)


class AmendmentResponse(BaseModel):
    """Proposal amendment response returned to Project members."""

    id: UUID
    proposal_id: UUID
    proposed_by: UUID
    change_type: str
    before: dict[str, Any]
    after: dict[str, Any]
    reason: str
    status: str
    responded_at: datetime | None
    responded_by: UUID | None
    expires_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MilestoneCreateRequest(BaseModel):
    """Accepted Contributor request body for drafting a Project Milestone."""

    sequence: int = Field(gt=0, le=100)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4000)
    budget: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(
        default_factory=platform_currency,
        min_length=3,
        max_length=3,
    )
    due_date: date | None = None

    @field_validator("currency")
    @classmethod
    def currency_is_the_platform_currency(cls, value: str) -> str:
        """Pin Milestone amounts to the platform's settlement currency."""
        return normalize_platform_currency(value)


class MilestoneUpdateRequest(BaseModel):
    """Accepted Contributor request body for editing a draft Milestone."""

    sequence: int | None = Field(default=None, gt=0, le=100)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, min_length=1, max_length=4000)
    budget: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
    )
    due_date: date | None = None


class MilestoneResponse(BaseModel):
    """Milestone response returned to Project members."""

    id: UUID
    project_id: UUID
    escrow_id: UUID | None
    sequence: int
    name: str
    description: str
    budget: Decimal
    currency: str
    due_date: date | None
    status: str
    funded_at: datetime | None
    submitted_at: datetime | None
    approved_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MilestonesResponse(BaseModel):
    """List response for Project Milestones."""

    milestones: list[MilestoneResponse]


class MilestoneFundingResponse(BaseModel):
    """Stripe PaymentIntent data needed to fund a Project Milestone."""

    transaction_id: UUID
    provider: Literal["stripe"]
    client_secret: str


class DeliverableSubmitRequest(BaseModel):
    """Accepted Contributor request body for submitting Milestone work."""

    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4000)
    file_keys: list[str] = Field(min_length=1, max_length=10)


class DeliverableRevisionRequest(BaseModel):
    """Operator request body for sending a Deliverable back for revision."""

    revision_notes: str = Field(min_length=5, max_length=4000)


class DeliverableResponse(BaseModel):
    """Deliverable response returned to Project members."""

    id: UUID
    milestone_id: UUID
    contributor_id: UUID | None
    contributor_org_id: UUID | None = None
    name: str
    description: str
    file_keys: list[str]
    revision_notes: str | None
    status: str
    scan_status: str
    submitted_at: datetime
    approved_at: datetime | None
    auto_approved: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeliverablesResponse(BaseModel):
    """List of Deliverables submitted against a Milestone."""

    deliverables: list[DeliverableResponse]


class DeliverableFileDownload(BaseModel):
    """A single downloadable Deliverable file with a presigned URL."""

    file_key: str
    file_name: str
    url: str


class DeliverableDownloadResponse(BaseModel):
    """Presigned download targets for a Deliverable's files."""

    files: list[DeliverableFileDownload]


class FrameworkPrefillResponse(BaseModel):
    """Framework draft prefill data derived from an approved Deliverable."""

    title: str
    description: str
    file_keys: list[str]
    tags: list[str] = Field(default_factory=lambda: ["project-deliverable"])
    source_project_id: UUID
    source_deliverable_id: UUID


class DisputeCreateRequest(BaseModel):
    """Project member request body for raising a Milestone dispute."""

    milestone_id: UUID
    reason: str = Field(min_length=10, max_length=10000)


class DisputeResponse(BaseModel):
    """Dispute response returned to Project members and Admins."""

    id: UUID
    project_id: UUID
    milestone_id: UUID
    # Which side opened the dispute ("operator"/"contributor"). The raiser's
    # user id is deliberately not exposed: on org projects it would reveal the
    # acting member to the counterparty. Admins get the raiser via
    # AdminDisputeResponse.raised_by_name.
    raised_by_side: str | None
    reason: str
    status: str
    resolution_type: str | None
    release_amount: Decimal | None
    refund_amount: Decimal | None
    admin_id: UUID | None
    resolution_notes: str | None
    escalated_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DisputesResponse(BaseModel):
    """List response for Project Disputes."""

    disputes: list[DisputeResponse]


class AdminDisputeResponse(DisputeResponse):
    """Dispute enriched with the context an Admin needs to resolve it.

    Adds the milestone budget, currently-held escrow amount, project title, and
    the name of the party who raised the dispute so the resolver can choose a
    release/refund/split amount without leaving the queue.
    """

    project_title: str
    milestone_name: str
    milestone_budget: Decimal
    currency: str
    escrow_amount: Decimal | None
    escrow_status: str | None
    raised_by_name: str | None
    raised_by_role: str
    operator_name: str
    contributor_name: str


class AdminDisputesResponse(BaseModel):
    """Admin list response for Project Disputes with resolution context."""

    disputes: list[AdminDisputeResponse]


class ProjectResponse(BaseModel):
    """Project response returned by CRUD and assignment endpoints.

    ``operator_id`` is set for individually-operated Projects and ``None`` for
    organization-operated Projects, which instead carry ``operator_org_id``.
    ``operator_name`` resolves to the Operator's display name or, for an
    organization-operated Project, the Organization name. The internal
    ``posting_member_id`` provenance field is never exposed here.
    """

    id: UUID
    operator_id: UUID | None = None
    operator_org_id: UUID | None = None
    operator_name: str | None = None
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
    operator_reputation: ReputationSummary | None = None

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
    contributor_id: UUID | None
    contributor_org_id: UUID | None = None
    contributor_name: str | None = None
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


class OrgDeliveryResponse(BaseModel):
    """Organization-internal view of one accepted Project delivery workspace."""

    proposal_id: UUID
    project_id: UUID
    project_title: str
    project_status: str
    milestone_plan_status: str
    delivering_member_id: UUID | None
    accepted_at: datetime | None
    created_at: datetime


class OrgDeliveriesResponse(BaseModel):
    """List of active organization delivery workspaces."""

    deliveries: list[OrgDeliveryResponse]
