"""Add access-token revocation cutoff for admin user suspension.

Supports Phase 5d Slice 6 by storing a user-level timestamp that invalidates
pre-suspension access tokens even after an admin later unsuspends the account.

Revision ID: 2026_06_12_0024
Revises: 2026_06_12_0023
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "2026_06_12_0024"
down_revision = "2026_06_12_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the user-level access-token revocation cutoff column."""
    op.add_column(
        "users",
        sa.Column("access_revoked_before", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove the user-level access-token revocation cutoff column."""
    op.drop_column("users", "access_revoked_before")
