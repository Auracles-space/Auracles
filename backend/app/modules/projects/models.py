"""SQLAlchemy models for Phase 4a Projects.

These schema-first models define Projects, Proposals, Amendments, Milestones,
Deliverables, and Disputes. Later slices add service methods and API endpoints
that enforce the state machines described in the Phase 4a design spec.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models.base import CreatedAtMixin, UpdatedAtMixin

PROJECT_STATUS_ENUM = ENUM(
    "open",
    "assigned",
    "in_progress",
    "delivered",
    "closed",
    "disputed",
    name="project_status_enum",
    create_type=False,
)
MILESTONE_PLAN_STATUS_ENUM = ENUM(
    "draft",
    "finalized",
    name="milestone_plan_status_enum",
    create_type=False,
)
PROPOSAL_STATUS_ENUM = ENUM(
    "pending",
    "accepted",
    "rejected",
    "withdrawn",
    name="proposal_status_enum",
    create_type=False,
)
AMENDMENT_CHANGE_ENUM = ENUM(
    "scope",
    "budget",
    "timeline",
    "combo",
    name="amendment_change_enum",
    create_type=False,
)
AMENDMENT_STATUS_ENUM = ENUM(
    "pending",
    "accepted",
    "rejected",
    "withdrawn",
    "expired",
    name="amendment_status_enum",
    create_type=False,
)
MILESTONE_STATUS_ENUM = ENUM(
    "pending",
    "funded",
    "submitted",
    "approved",
    "revision_requested",
    "disputed",
    "auto_approved",
    "cancelled",
    name="milestone_status_enum",
    create_type=False,
)
DELIVERABLE_STATUS_ENUM = ENUM(
    "submitted",
    "approved",
    "revision_requested",
    "auto_approved",
    name="deliverable_status_enum",
    create_type=False,
)
DELIVERABLE_SCAN_STATUS_ENUM = ENUM(
    "pending_scan",
    "visible",
    "quarantined",
    name="deliverable_scan_status_enum",
    create_type=False,
)
DISPUTE_STATUS_ENUM = ENUM(
    "open",
    "under_review",
    "resolved",
    name="dispute_status_enum",
    create_type=False,
)
DISPUTE_RESOLUTION_ENUM = ENUM(
    "release",
    "refund",
    "split",
    name="dispute_resolution_enum",
    create_type=False,
)


class Project(UpdatedAtMixin, Base):
    """Operator-posted request for custom framework work."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("budget_min <= budget_max", name="ck_projects_budget_range"),
        CheckConstraint("currency = 'USD'", name="ck_projects_currency_usd"),
        Index("idx_projects_operator_status", "operator_id", "status"),
        Index("idx_projects_status_expires_at", "status", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    operator_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    required_deliverables: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
    )
    budget_min: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    budget_max: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        server_default="USD",
    )
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        PROJECT_STATUS_ENUM,
        nullable=False,
        server_default="open",
    )
    milestone_plan_status: Mapped[str] = mapped_column(
        MILESTONE_PLAN_STATUS_ENUM,
        nullable=False,
        server_default="draft",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    accepted_proposal_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "proposals.id",
            deferrable=True,
            initially="DEFERRED",
            name="fk_projects_accepted_proposal_id_proposals",
            use_alter=True,
        ),
        nullable=True,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class Proposal(CreatedAtMixin, Base):
    """Contributor bid against an open Project."""

    __tablename__ = "proposals"
    __table_args__ = (
        CheckConstraint("budget > 0", name="ck_proposals_budget_positive"),
        CheckConstraint("currency = 'USD'", name="ck_proposals_currency_usd"),
        CheckConstraint("timeline_days > 0", name="ck_proposals_timeline_positive"),
        CheckConstraint(
            "(contributor_id IS NULL) != (contributor_org_id IS NULL)",
            name="ck_proposals_seller_xor",
        ),
        Index("idx_proposals_project_status", "project_id", "status"),
        Index("idx_proposals_contributor_status", "contributor_id", "status"),
        Index(
            "uq_proposals_project_contributor_active",
            "project_id",
            "contributor_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'accepted')"),
        ),
        Index(
            "uq_proposals_project_org_active",
            "project_id",
            "contributor_org_id",
            unique=True,
            postgresql_where=text(
                "contributor_org_id IS NOT NULL AND status IN ('pending', 'accepted')"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    contributor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    contributor_org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=True,
    )
    delivering_member_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("org_members.id", ondelete="SET NULL"),
        nullable=True,
    )
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    budget: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        server_default="USD",
    )
    timeline_days: Mapped[int] = mapped_column(Integer, nullable=False)
    deliverables: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        PROPOSAL_STATUS_ENUM,
        nullable=False,
        server_default="pending",
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ProposalAmendment(CreatedAtMixin, Base):
    """Audited proposal change that requires counter-party acceptance."""

    __tablename__ = "proposal_amendments"
    __table_args__ = (
        Index("idx_proposal_amendments_status_expires_at", "status", "expires_at"),
        Index(
            "uq_proposal_amendments_proposal_pending",
            "proposal_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    proposal_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("proposals.id", ondelete="CASCADE"),
        nullable=False,
    )
    proposed_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    change_type: Mapped[str] = mapped_column(AMENDMENT_CHANGE_ENUM, nullable=False)
    before: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        AMENDMENT_STATUS_ENUM,
        nullable=False,
        server_default="pending",
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    responded_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class Milestone(CreatedAtMixin, Base):
    """Escrow-backed unit of work inside an accepted Project."""

    __tablename__ = "milestones"
    __table_args__ = (
        CheckConstraint("budget > 0", name="ck_milestones_budget_positive"),
        CheckConstraint("currency = 'USD'", name="ck_milestones_currency_usd"),
        UniqueConstraint(
            "project_id",
            "sequence",
            name="uq_milestones_project_sequence",
        ),
        Index("idx_milestones_project_status", "project_id", "status"),
        Index("idx_milestones_status_submitted_at", "status", "submitted_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    escrow_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("escrows.id", ondelete="RESTRICT"),
        nullable=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    budget: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        server_default="USD",
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        MILESTONE_STATUS_ENUM,
        nullable=False,
        server_default="pending",
    )
    funded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class Deliverable(CreatedAtMixin, Base):
    """Contributor-submitted output for a Milestone."""

    __tablename__ = "deliverables"
    __table_args__ = (
        CheckConstraint(
            "(contributor_id IS NULL) != (contributor_org_id IS NULL)",
            name="ck_deliverables_seller_xor",
        ),
        Index("idx_deliverables_milestone_status", "milestone_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    milestone_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("milestones.id", ondelete="CASCADE"),
        nullable=False,
    )
    contributor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    contributor_org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    file_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    revision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        DELIVERABLE_STATUS_ENUM,
        nullable=False,
        server_default="submitted",
    )
    scan_status: Mapped[str] = mapped_column(
        DELIVERABLE_SCAN_STATUS_ENUM,
        nullable=False,
        server_default="pending_scan",
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    auto_approved: Mapped[bool] = mapped_column(
        nullable=False,
        server_default=text("false"),
    )


class Dispute(CreatedAtMixin, Base):
    """Milestone dispute raised by a project party and resolved by Admin."""

    __tablename__ = "disputes"
    __table_args__ = (
        CheckConstraint(
            "status != 'resolved' OR resolution_type IS NOT NULL",
            name="ck_disputes_resolved_has_resolution_type",
        ),
        CheckConstraint(
            "resolution_type != 'split' "
            "OR (release_amount IS NOT NULL AND refund_amount IS NOT NULL)",
            name="ck_disputes_split_has_amounts",
        ),
        Index("idx_disputes_project_status", "project_id", "status"),
        Index("idx_disputes_status_created_at", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    milestone_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("milestones.id", ondelete="RESTRICT"),
        nullable=False,
    )
    raised_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        DISPUTE_STATUS_ENUM,
        nullable=False,
        server_default="open",
    )
    resolution_type: Mapped[str | None] = mapped_column(
        DISPUTE_RESOLUTION_ENUM,
        nullable=True,
    )
    release_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    refund_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    admin_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
