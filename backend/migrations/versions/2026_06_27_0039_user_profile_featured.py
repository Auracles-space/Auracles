"""Add featured spotlights to users for the Auracles Profile.

A small owner-curated "Featured" section (flagship framework, case study, or
milestone) shown at the top of the profile. Stored as a JSONB array edited as a
whole via PATCH /profiles/me. Defaults to empty; existing users have none.

Revision ID: 2026_06_27_0039
Revises: 2026_06_27_0038
Create Date: 2026-06-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_27_0039"
down_revision: str | Sequence[str] | None = "2026_06_27_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the featured JSONB column to users."""
    op.add_column(
        "users",
        sa.Column(
            "featured",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    """Drop the featured column from users."""
    op.drop_column("users", "featured")
