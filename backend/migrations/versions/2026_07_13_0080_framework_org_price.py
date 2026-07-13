"""Add frameworks.org_price for the organizational license pricing tier.

Additive, nullable column plus a positivity CHECK. NULL means the org tier is
either not offered or reuses the single-user price. Supports the per-org
pricing feature (docs/superpowers/specs/2026-07-13-per-org-framework-pricing-design.md).

Revision ID: 2026_07_13_0080
Revises: 2026_07_11_0079
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_13_0080"
down_revision: str | Sequence[str] | None = "2026_07_11_0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable org_price column and its positivity CHECK."""
    op.add_column(
        "frameworks",
        sa.Column("org_price", sa.Numeric(12, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_frameworks_org_price_positive",
        "frameworks",
        "org_price IS NULL OR org_price > 0",
    )


def downgrade() -> None:
    """Drop the org_price CHECK and column."""
    op.drop_constraint("ck_frameworks_org_price_positive", "frameworks", type_="check")
    op.drop_column("frameworks", "org_price")
