"""Add waitlist_entries table for pre-launch marketing signups.

Stores one row per unique, normalized email captured from the public landing
page. The unique constraint on ``email`` enforces deduplication so the same
address can never be recorded twice.

Revision ID: 2026_06_23_0033
Revises: 2026_06_21_0032
Create Date: 2026-06-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_23_0033"
down_revision: str | Sequence[str] | None = "2026_06_21_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the waitlist_entries table with a unique email constraint."""
    op.create_table(
        "waitlist_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_waitlist_entries_email"),
    )
    op.create_index(
        "idx_waitlist_entries_created_at", "waitlist_entries", ["created_at"]
    )


def downgrade() -> None:
    """Drop the waitlist_entries table and its index."""
    op.drop_index("idx_waitlist_entries_created_at", table_name="waitlist_entries")
    op.drop_table("waitlist_entries")
