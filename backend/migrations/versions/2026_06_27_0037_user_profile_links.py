"""Add portfolio links to users for the Auracles Profile.

Portfolio links (label + URL pairs) shown on the profile, stored as a JSONB
array edited as a whole via PATCH /profiles/me. Defaults to an empty array;
existing users simply have none.

Revision ID: 2026_06_27_0037
Revises: 2026_06_27_0036
Create Date: 2026-06-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_27_0037"
down_revision: str | Sequence[str] | None = "2026_06_27_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the links JSONB column to users."""
    op.add_column(
        "users",
        sa.Column(
            "links",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    """Drop the links column from users."""
    op.drop_column("users", "links")
