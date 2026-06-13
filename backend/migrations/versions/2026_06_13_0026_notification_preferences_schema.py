"""Add notification preference schema foundation.

Supports the notification-preferences Slice 1 by creating durable per-user
event/channel override rows and the category/channel enum types later settings
and worker slices depend on.

Revision ID: 2026_06_13_0026
Revises: 2026_06_13_0025
Create Date: 2026-06-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_13_0026"
down_revision: str | Sequence[str] | None = "2026_06_13_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOTIFICATION_CHANNEL_ENUM = postgresql.ENUM(
    "email",
    "in_app",
    name="notification_channel_enum",
    create_type=False,
)
NOTIFICATION_CATEGORY_ENUM = postgresql.ENUM(
    "project",
    "attestation",
    "financial",
    "discovery",
    "account",
    name="notification_category_enum",
    create_type=False,
)


def upgrade() -> None:
    """Create notification preference enums, table, and supporting indexes."""
    bind = op.get_bind()
    NOTIFICATION_CHANNEL_ENUM.create(bind, checkfirst=True)
    NOTIFICATION_CATEGORY_ENUM.create(bind, checkfirst=True)

    op.create_table(
        "notification_preferences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "notification_type",
            postgresql.ENUM(
                name="notification_type_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("category", NOTIFICATION_CATEGORY_ENUM, nullable=False),
        sa.Column("channel", NOTIFICATION_CHANNEL_ENUM, nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
        sa.UniqueConstraint(
            "user_id",
            "notification_type",
            "channel",
            name="uq_notification_preferences_user_type_channel",
        ),
    )
    op.create_index(
        "idx_notification_preferences_user_type",
        "notification_preferences",
        ["user_id", "notification_type"],
    )


def downgrade() -> None:
    """Drop notification preference schema objects."""
    bind = op.get_bind()
    op.drop_index(
        "idx_notification_preferences_user_type",
        table_name="notification_preferences",
    )
    op.drop_table("notification_preferences")
    NOTIFICATION_CATEGORY_ENUM.drop(bind, checkfirst=True)
    NOTIFICATION_CHANNEL_ENUM.drop(bind, checkfirst=True)
