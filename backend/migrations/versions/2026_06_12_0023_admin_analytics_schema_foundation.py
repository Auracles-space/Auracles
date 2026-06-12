"""Add admin analytics snapshot table and user suspension columns.

Supports Phase 5d Slice 1 by introducing the durable daily analytics snapshot
table and the reversible user suspension metadata used by later admin slices.

Revision ID: 2026_06_12_0023
Revises: 2026_06_12_0022
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "2026_06_12_0023"
down_revision = "2026_06_12_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create admin analytics snapshot storage and user suspension columns."""
    op.create_table(
        "analytics_daily_snapshots",
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("gmv_total", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "gmv_by_source",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("active_users", sa.Integer(), nullable=False),
        sa.Column("new_registrations", sa.Integer(), nullable=False),
        sa.Column("frameworks_published", sa.Integer(), nullable=False),
        sa.Column("attestations_issued", sa.Integer(), nullable=False),
        sa.Column("disputes_open", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_date"),
    )
    op.create_index(
        "idx_analytics_daily_snapshots_computed_at",
        "analytics_daily_snapshots",
        ["computed_at"],
        unique=False,
    )

    op.add_column(
        "users",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "suspended_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column("suspension_reason", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_suspended_by_users",
        "users",
        "users",
        ["suspended_by"],
        ["id"],
    )
    op.create_index(
        "idx_users_suspended_at_not_null",
        "users",
        ["suspended_at"],
        unique=False,
        postgresql_where=sa.text("suspended_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove admin analytics snapshot storage and user suspension columns."""
    op.drop_index("idx_users_suspended_at_not_null", table_name="users")
    op.drop_constraint("fk_users_suspended_by_users", "users", type_="foreignkey")
    op.drop_column("users", "suspension_reason")
    op.drop_column("users", "suspended_by")
    op.drop_column("users", "suspended_at")

    op.drop_index(
        "idx_analytics_daily_snapshots_computed_at",
        table_name="analytics_daily_snapshots",
    )
    op.drop_table("analytics_daily_snapshots")
