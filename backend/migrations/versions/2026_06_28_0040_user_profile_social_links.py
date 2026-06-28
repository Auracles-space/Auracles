"""Add typed social links to users for the Auracles Profile.

Typed social links (platform + URL pairs, one per platform) shown on the
profile, stored as a JSONB array edited as a whole via PATCH /profiles/me.
Distinct from the free-form portfolio ``links`` so the frontend can render a
per-platform icon. Defaults to an empty array; existing users simply have none.

Revision ID: 2026_06_28_0040
Revises: 2026_06_27_0039
Create Date: 2026-06-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_28_0040"
down_revision: str | Sequence[str] | None = "2026_06_27_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the social_links JSONB column to users."""
    op.add_column(
        "users",
        sa.Column(
            "social_links",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    """Drop the social_links column from users."""
    op.drop_column("users", "social_links")
