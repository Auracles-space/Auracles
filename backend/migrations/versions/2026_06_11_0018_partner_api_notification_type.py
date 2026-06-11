"""Add Partner API rate-limit notification type.

Supports Phase 5a Slice 4 by allowing the API-key rate limiter to create a
durable user notification when a Partner key reaches the 80% usage threshold.

Revision ID: 2026_06_11_0018
Revises: 2026_06_11_0017
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_06_11_0018"
down_revision: str | Sequence[str] | None = "2026_06_11_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add Partner API threshold notification label."""
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
        "'api_rate_limit_threshold'"
    )


def downgrade() -> None:
    """Leave additive notification enum label in place on downgrade."""
    op.execute(
        "DELETE FROM notifications WHERE type::text = 'api_rate_limit_threshold'"
    )
