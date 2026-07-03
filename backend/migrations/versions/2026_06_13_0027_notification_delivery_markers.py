"""Add notification delivery markers for email-only deduplication.

Supports the notification-preferences reviewer follow-up by preserving
idempotent email fanout when in-app notification rows are intentionally
suppressed by user preferences.

Revision ID: 2026_06_13_0027
Revises: 2026_06_13_0026
Create Date: 2026-06-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_13_0027"
down_revision: str | Sequence[str] | None = "2026_06_13_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the durable notification delivery marker table."""
    op.create_table(
        "notification_delivery_markers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column(
            "channel",
            postgresql.ENUM(
                name="notification_channel_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id",
            "dedupe_key",
            "channel",
            name="uq_notification_delivery_markers_user_dedupe_channel",
        ),
    )


def downgrade() -> None:
    """Drop the notification delivery marker table."""
    op.drop_table("notification_delivery_markers")
