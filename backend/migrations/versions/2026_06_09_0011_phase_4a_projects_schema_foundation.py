"""Create Phase 4a projects schema foundation.

Revision ID: 2026_06_09_0011
Revises: 2026_06_09_0010
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_09_0011"
down_revision: str | Sequence[str] | None = "2026_06_09_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

project_status_enum = postgresql.ENUM(
    "open",
    "assigned",
    "in_progress",
    "delivered",
    "closed",
    "disputed",
    name="project_status_enum",
    create_type=False,
)
milestone_plan_status_enum = postgresql.ENUM(
    "draft",
    "finalized",
    name="milestone_plan_status_enum",
    create_type=False,
)
proposal_status_enum = postgresql.ENUM(
    "pending",
    "accepted",
    "rejected",
    "withdrawn",
    name="proposal_status_enum",
    create_type=False,
)
amendment_change_enum = postgresql.ENUM(
    "scope",
    "budget",
    "timeline",
    "combo",
    name="amendment_change_enum",
    create_type=False,
)
amendment_status_enum = postgresql.ENUM(
    "pending",
    "accepted",
    "rejected",
    "withdrawn",
    "expired",
    name="amendment_status_enum",
    create_type=False,
)
milestone_status_enum = postgresql.ENUM(
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
deliverable_status_enum = postgresql.ENUM(
    "submitted",
    "approved",
    "revision_requested",
    "auto_approved",
    name="deliverable_status_enum",
    create_type=False,
)
workspace_scan_status_enum = postgresql.ENUM(
    "pending_scan",
    "visible",
    "quarantined",
    name="workspace_scan_status_enum",
    create_type=False,
)
workspace_system_event_enum = postgresql.ENUM(
    "amendment_proposed",
    "amendment_accepted",
    "amendment_rejected",
    "amendment_expired",
    "milestone_funded",
    "deliverable_submitted",
    "deliverable_approved",
    "deliverable_auto_approved",
    "deliverable_revision_requested",
    "dispute_raised",
    "dispute_resolved",
    name="workspace_system_event_enum",
    create_type=False,
)
dispute_status_enum = postgresql.ENUM(
    "open",
    "under_review",
    "resolved",
    name="dispute_status_enum",
    create_type=False,
)
dispute_resolution_enum = postgresql.ENUM(
    "release",
    "refund",
    "split",
    name="dispute_resolution_enum",
    create_type=False,
)
notification_type_enum = postgresql.ENUM(
    "project_created",
    "project_extended",
    "project_closed",
    "proposal_submitted",
    "proposal_accepted",
    "proposal_rejected",
    "proposal_withdrawn",
    "proposal_expired",
    "amendment_proposed",
    "amendment_accepted",
    "amendment_rejected",
    "amendment_withdrawn",
    "amendment_expired",
    "milestone_created",
    "milestone_updated",
    "milestone_funded",
    "deliverable_submitted",
    "deliverable_approved",
    "deliverable_auto_approved",
    "deliverable_revision_requested",
    "dispute_raised",
    "dispute_escalated",
    "dispute_resolved_release",
    "dispute_resolved_refund",
    "dispute_resolved_split",
    "workspace_file_quarantined",
    "attestation_requested",
    "attestation_assigned",
    "attestation_report_submitted",
    "attestation_published",
    "attestation_rejected",
    name="notification_type_enum",
    create_type=False,
)


def upgrade() -> None:
    """Apply Phase 4a Slice 1 projects, workspace, and notification schema."""
    bind = op.get_bind()

    project_status_enum.create(bind, checkfirst=True)
    milestone_plan_status_enum.create(bind, checkfirst=True)
    proposal_status_enum.create(bind, checkfirst=True)
    amendment_change_enum.create(bind, checkfirst=True)
    amendment_status_enum.create(bind, checkfirst=True)
    milestone_status_enum.create(bind, checkfirst=True)
    deliverable_status_enum.create(bind, checkfirst=True)
    workspace_scan_status_enum.create(bind, checkfirst=True)
    workspace_system_event_enum.create(bind, checkfirst=True)
    dispute_status_enum.create(bind, checkfirst=True)
    dispute_resolution_enum.create(bind, checkfirst=True)
    notification_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("required_deliverables", postgresql.JSONB(), nullable=False),
        sa.Column("budget_min", sa.Numeric(12, 2), nullable=False),
        sa.Column("budget_max", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column(
            "status",
            project_status_enum,
            nullable=False,
            server_default="open",
        ),
        sa.Column(
            "milestone_plan_status",
            milestone_plan_status_enum,
            nullable=False,
            server_default="draft",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_proposal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("budget_min <= budget_max", name="ck_projects_budget_range"),
        sa.CheckConstraint("currency = 'USD'", name="ck_projects_currency_usd"),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"]),
    )
    op.create_index(
        "idx_projects_operator_status",
        "projects",
        ["operator_id", "status"],
    )
    op.create_index(
        "idx_projects_status_expires_at",
        "projects",
        ["status", "expires_at"],
    )

    op.create_table(
        "proposals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contributor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("budget", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
        sa.Column("timeline_days", sa.Integer(), nullable=False),
        sa.Column("deliverables", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            proposal_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("budget > 0", name="ck_proposals_budget_positive"),
        sa.CheckConstraint("currency = 'USD'", name="ck_proposals_currency_usd"),
        sa.CheckConstraint("timeline_days > 0", name="ck_proposals_timeline_positive"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_proposals_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["contributor_id"], ["users.id"]),
    )
    op.create_index(
        "idx_proposals_project_status",
        "proposals",
        ["project_id", "status"],
    )
    op.create_index(
        "idx_proposals_contributor_status",
        "proposals",
        ["contributor_id", "status"],
    )
    op.create_index(
        "uq_proposals_project_contributor_active",
        "proposals",
        ["project_id", "contributor_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'accepted')"),
    )
    op.create_foreign_key(
        "fk_projects_accepted_proposal_id_proposals",
        "projects",
        "proposals",
        ["accepted_proposal_id"],
        ["id"],
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "proposal_amendments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposed_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_type", amendment_change_enum, nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=False),
        sa.Column("after", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            amendment_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposals.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["proposed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["responded_by"], ["users.id"]),
    )
    op.create_index(
        "idx_proposal_amendments_status_expires_at",
        "proposal_amendments",
        ["status", "expires_at"],
    )
    op.create_index(
        "uq_proposal_amendments_proposal_pending",
        "proposal_amendments",
        ["proposal_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "milestones",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("escrow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("budget", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            milestone_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("funded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("budget > 0", name="ck_milestones_budget_positive"),
        sa.CheckConstraint("currency = 'USD'", name="ck_milestones_currency_usd"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["escrow_id"],
            ["escrows.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "sequence",
            name="uq_milestones_project_sequence",
        ),
    )
    op.create_index(
        "idx_milestones_project_status",
        "milestones",
        ["project_id", "status"],
    )
    op.create_index(
        "idx_milestones_status_submitted_at",
        "milestones",
        ["status", "submitted_at"],
    )

    op.create_table(
        "deliverables",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("milestone_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contributor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("file_keys", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("revision_notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            deliverable_status_enum,
            nullable=False,
            server_default="submitted",
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "auto_approved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["milestone_id"],
            ["milestones.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["contributor_id"], ["users.id"]),
    )
    op.create_index(
        "idx_deliverables_milestone_status",
        "deliverables",
        ["milestone_id", "status"],
    )

    op.create_table(
        "workspace_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("file_keys", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "scan_status",
            workspace_scan_status_enum,
            nullable=False,
            server_default="visible",
        ),
        sa.Column("system_event", workspace_system_event_enum, nullable=True),
        sa.Column("system_payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "(sender_id IS NOT NULL AND (body IS NOT NULL OR file_keys IS NOT NULL)) "
            "OR (sender_id IS NULL AND system_event IS NOT NULL)",
            name="ck_workspace_messages_sender_or_system_event",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"]),
    )
    op.execute(
        """
        CREATE INDEX idx_workspace_messages_project_created_at
        ON workspace_messages (project_id, created_at DESC)
        """
    )
    op.create_index(
        "idx_workspace_messages_pending_scan",
        "workspace_messages",
        ["scan_status"],
        postgresql_where=sa.text("scan_status = 'pending_scan'"),
    )

    op.create_table(
        "workspace_upload_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("s3_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_limit", sa.Integer(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("s3_key", name="uq_workspace_upload_sessions_s3_key"),
    )
    op.create_index(
        "idx_workspace_upload_sessions_project_user_consumed",
        "workspace_upload_sessions",
        ["project_id", "user_id", "consumed_at"],
    )
    op.create_index(
        "idx_workspace_upload_sessions_expires_at",
        "workspace_upload_sessions",
        ["expires_at"],
    )

    op.create_table(
        "disputes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("milestone_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raised_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            dispute_status_enum,
            nullable=False,
            server_default="open",
        ),
        sa.Column("resolution_type", dispute_resolution_enum, nullable=True),
        sa.Column("release_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("refund_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status != 'resolved' OR resolution_type IS NOT NULL",
            name="ck_disputes_resolved_has_resolution_type",
        ),
        sa.CheckConstraint(
            "resolution_type != 'split' "
            "OR (release_amount IS NOT NULL AND refund_amount IS NOT NULL)",
            name="ck_disputes_split_has_amounts",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["milestone_id"],
            ["milestones.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["raised_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"]),
    )
    op.create_index(
        "idx_disputes_project_status",
        "disputes",
        ["project_id", "status"],
    )
    op.create_index(
        "idx_disputes_status_created_at",
        "disputes",
        ["status", "created_at"],
    )

    op.create_table(
        "notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", notification_type_enum, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.execute(
        """
        CREATE INDEX idx_notifications_user_read_created
        ON notifications (user_id, read_at NULLS FIRST, created_at DESC)
        """
    )
    op.create_index(
        "uq_notifications_user_dedupe_key",
        "notifications",
        ["user_id", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove Phase 4a Slice 1 project schema additions."""
    bind = op.get_bind()

    op.drop_index("uq_notifications_user_dedupe_key", table_name="notifications")
    op.execute("DROP INDEX IF EXISTS idx_notifications_user_read_created")
    op.drop_table("notifications")

    op.drop_index("idx_disputes_status_created_at", table_name="disputes")
    op.drop_index("idx_disputes_project_status", table_name="disputes")
    op.drop_table("disputes")

    op.drop_index(
        "idx_workspace_upload_sessions_expires_at",
        table_name="workspace_upload_sessions",
    )
    op.drop_index(
        "idx_workspace_upload_sessions_project_user_consumed",
        table_name="workspace_upload_sessions",
    )
    op.drop_table("workspace_upload_sessions")

    op.drop_index(
        "idx_workspace_messages_pending_scan",
        table_name="workspace_messages",
    )
    op.execute("DROP INDEX IF EXISTS idx_workspace_messages_project_created_at")
    op.drop_table("workspace_messages")

    op.drop_index("idx_deliverables_milestone_status", table_name="deliverables")
    op.drop_table("deliverables")

    op.drop_index("idx_milestones_status_submitted_at", table_name="milestones")
    op.drop_index("idx_milestones_project_status", table_name="milestones")
    op.drop_table("milestones")

    op.drop_index(
        "uq_proposal_amendments_proposal_pending",
        table_name="proposal_amendments",
    )
    op.drop_index(
        "idx_proposal_amendments_status_expires_at",
        table_name="proposal_amendments",
    )
    op.drop_table("proposal_amendments")

    op.drop_constraint(
        "fk_projects_accepted_proposal_id_proposals",
        "projects",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_proposals_project_contributor_active",
        table_name="proposals",
    )
    op.drop_index("idx_proposals_contributor_status", table_name="proposals")
    op.drop_index("idx_proposals_project_status", table_name="proposals")
    op.drop_table("proposals")

    op.drop_index("idx_projects_status_expires_at", table_name="projects")
    op.drop_index("idx_projects_operator_status", table_name="projects")
    op.drop_table("projects")

    notification_type_enum.drop(bind, checkfirst=True)
    dispute_resolution_enum.drop(bind, checkfirst=True)
    dispute_status_enum.drop(bind, checkfirst=True)
    workspace_system_event_enum.drop(bind, checkfirst=True)
    workspace_scan_status_enum.drop(bind, checkfirst=True)
    deliverable_status_enum.drop(bind, checkfirst=True)
    milestone_status_enum.drop(bind, checkfirst=True)
    amendment_status_enum.drop(bind, checkfirst=True)
    amendment_change_enum.drop(bind, checkfirst=True)
    proposal_status_enum.drop(bind, checkfirst=True)
    milestone_plan_status_enum.drop(bind, checkfirst=True)
    project_status_enum.drop(bind, checkfirst=True)
