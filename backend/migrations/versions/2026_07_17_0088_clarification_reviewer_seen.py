"""Add reviewer_seen_at to attestation clarifications.

The reviewer queue shows an "answer received" dot when the requestor has
answered a clarification the reviewer has not yet read. That unread state needs
a per-clarification marker: reviewer_seen_at is null until the reviewer opens
the answer, at which point it is stamped and the dot clears.

Revision ID: 2026_07_17_0088
Revises: 2026_07_17_0087
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_17_0088"
down_revision: str | Sequence[str] | None = "2026_07_17_0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable reviewer_seen_at timestamp column."""
    op.add_column(
        "attestation_clarifications",
        sa.Column("reviewer_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Drop the reviewer_seen_at column."""
    op.drop_column("attestation_clarifications", "reviewer_seen_at")
