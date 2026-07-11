"""Add organization billing email for org-as-buyer purchase invoices.

Supports org purchase invoices (organizations as Operators) by recording an
explicit billing contact for the invoice buyer field. The column is additive
and nullable; issuance falls back to the org owner's email when it is unset.

Revision ID: 2026_07_11_0077
Revises: 2026_07_10_0076
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_11_0077"
down_revision: str | Sequence[str] | None = "2026_07_10_0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable ``billing_email`` column to organizations."""
    op.add_column(
        "organizations",
        sa.Column("billing_email", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    """Drop the organization ``billing_email`` column."""
    op.drop_column("organizations", "billing_email")
