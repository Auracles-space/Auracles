"""Add is_superadmin flag to users for protected platform-config control.

The bootstrap admin is marked ``is_superadmin`` so it cannot be suspended by
other admins and is the only account allowed to change platform configuration.
Existing users default to ``false``; the flag is set explicitly by
``scripts.bootstrap_admin`` or a deliberate DB action.

Revision ID: 2026_06_21_0032
Revises: 2026_06_21_0031
Create Date: 2026-06-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_06_21_0032"
down_revision: str | Sequence[str] | None = "2026_06_21_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the is_superadmin boolean, defaulting existing users to false."""
    op.add_column(
        "users",
        sa.Column(
            "is_superadmin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    """Drop the is_superadmin column."""
    op.drop_column("users", "is_superadmin")
