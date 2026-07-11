"""Add artifact content hash and processing lease for connector re-sync.

Supports Connectors Phase C: ``content_sha256`` lets re-sync skip forking an
identical byte copy, and ``processing_started_at`` drives the stale-lease
reaper plus the TTL-aware in-flight guard. Both are additive and nullable;
existing rows keep NULL (no backfill needed).

Revision ID: 2026_07_11_0079
Revises: 2026_07_11_0078
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_11_0079"
down_revision: str | Sequence[str] | None = "2026_07_11_0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the content hash and processing lease columns."""
    op.add_column(
        "artifacts",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "artifacts",
        sa.Column(
            "processing_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Drop the Phase C columns."""
    op.drop_column("artifacts", "processing_started_at")
    op.drop_column("artifacts", "content_sha256")
