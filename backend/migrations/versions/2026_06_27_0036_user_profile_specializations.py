"""Add specializations to users for the Auracles Profile.

User-level domains of expertise shown on the profile, generalizing the
attestor-only specializations pattern to all roles. Stored as a Postgres text
array (matching attestor_profiles) with a GIN index for future matching.
Defaults to an empty array; existing users simply have none.

Revision ID: 2026_06_27_0036
Revises: 2026_06_27_0035
Create Date: 2026-06-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_27_0036"
down_revision: str | Sequence[str] | None = "2026_06_27_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the specializations text-array column and its GIN index."""
    op.add_column(
        "users",
        sa.Column(
            "specializations",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.create_index(
        "idx_users_specializations_gin",
        "users",
        ["specializations"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Drop the specializations column and its index."""
    op.drop_index("idx_users_specializations_gin", table_name="users")
    op.drop_column("users", "specializations")
