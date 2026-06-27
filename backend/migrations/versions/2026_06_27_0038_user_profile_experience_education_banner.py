"""Add experience, education, and banner to users for the Auracles Profile.

CV-style sections for the profile: a structured (self-reported) professional
experience timeline and academic/education history, plus a profile banner image
served from the public avatars bucket. Experience and education are JSONB arrays
edited as a whole via PATCH /profiles/me; banner_url is set on confirmed upload.
All default to empty/null; existing users have none.

Revision ID: 2026_06_27_0038
Revises: 2026_06_27_0037
Create Date: 2026-06-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_27_0038"
down_revision: str | Sequence[str] | None = "2026_06_27_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add banner_url plus experience and education JSONB columns to users."""
    op.add_column("users", sa.Column("banner_url", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "experience",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "education",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    """Drop the experience, education, and banner columns from users."""
    op.drop_column("users", "education")
    op.drop_column("users", "experience")
    op.drop_column("users", "banner_url")
