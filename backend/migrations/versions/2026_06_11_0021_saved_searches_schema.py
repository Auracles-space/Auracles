"""Add saved-search schema foundation.

Supports Phase 5b-2 Slice 1 by creating Operator-owned saved search rows,
alert delivery idempotency rows, the published Framework scan index, the alert
notification type, and the default alert cadence platform config.

Revision ID: 2026_06_11_0021
Revises: 2026_06_11_0020
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_11_0021"
down_revision: str | Sequence[str] | None = "2026_06_11_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create saved-search tables, alert enum label, and scan config."""
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
        "'saved_search_alert'"
    )
    op.create_index(
        "idx_frameworks_status_published_at",
        "frameworks",
        ["status", "published_at"],
    )
    op.create_table(
        "saved_searches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "filters",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "filter_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "alert_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("last_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_alerted_framework_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["last_alerted_framework_id"],
            ["frameworks.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("user_id", "name", name="uq_saved_searches_user_name"),
    )
    op.create_index("idx_saved_searches_user", "saved_searches", ["user_id"])
    op.create_index(
        "idx_saved_searches_alerts",
        "saved_searches",
        ["user_id"],
        postgresql_where=sa.text("alert_enabled = true"),
    )

    op.create_table(
        "saved_search_alert_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("saved_search_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("framework_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["saved_search_id"],
            ["saved_searches.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["framework_id"],
            ["frameworks.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "saved_search_id",
            "framework_id",
            name="uq_saved_search_alert_deliveries_search_framework",
        ),
    )
    op.create_index(
        "idx_saved_search_alert_deliveries_search",
        "saved_search_alert_deliveries",
        ["saved_search_id"],
    )
    op.create_index(
        "idx_saved_search_alert_deliveries_framework",
        "saved_search_alert_deliveries",
        ["framework_id"],
    )
    op.execute(
        """
        INSERT INTO platform_config (key, value)
        VALUES ('saved_search_alert_cadence_hours', '24')
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    """Remove saved-search schema objects and default alert cadence config."""
    op.execute("DELETE FROM notifications WHERE type::text = 'saved_search_alert'")
    op.execute(
        "DELETE FROM platform_config WHERE key = 'saved_search_alert_cadence_hours'"
    )
    op.drop_index(
        "idx_saved_search_alert_deliveries_framework",
        table_name="saved_search_alert_deliveries",
    )
    op.drop_index(
        "idx_saved_search_alert_deliveries_search",
        table_name="saved_search_alert_deliveries",
    )
    op.drop_table("saved_search_alert_deliveries")
    op.drop_index("idx_saved_searches_alerts", table_name="saved_searches")
    op.drop_index("idx_saved_searches_user", table_name="saved_searches")
    op.drop_table("saved_searches")
    op.drop_index("idx_frameworks_status_published_at", table_name="frameworks")
