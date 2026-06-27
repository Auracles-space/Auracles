"""Add headline to users for the Auracles Profile.

The LinkedIn-style profile page needs a short professional headline distinct
from the longer free-text bio. Nullable; existing users simply have no
headline until they set one.

Revision ID: 2026_06_27_0035
Revises: 2026_06_24_0034
Create Date: 2026-06-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_06_27_0035"
down_revision: str | Sequence[str] | None = "2026_06_24_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable headline column to users."""
    op.add_column(
        "users",
        sa.Column("headline", sa.String(length=160), nullable=True),
    )


def downgrade() -> None:
    """Drop the headline column from users."""
    op.drop_column("users", "headline")
