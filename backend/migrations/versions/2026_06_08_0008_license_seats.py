"""Add license seat tracking columns.

Revision ID: 2026_06_08_0008
Revises: 2026_06_08_0007
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_06_08_0008"
down_revision: str | Sequence[str] | None = "2026_06_08_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add persisted seat counts for team and enterprise licenses."""
    op.add_column(
        "licenses",
        sa.Column(
            "seats_used",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "licenses",
        sa.Column("seats_total", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_licenses_seats_used_positive",
        "licenses",
        "seats_used >= 1",
    )
    op.create_check_constraint(
        "ck_licenses_seats_total_positive",
        "licenses",
        "seats_total IS NULL OR seats_total >= seats_used",
    )


def downgrade() -> None:
    """Remove persisted license seat counts."""
    op.drop_constraint(
        "ck_licenses_seats_total_positive",
        "licenses",
        type_="check",
    )
    op.drop_constraint(
        "ck_licenses_seats_used_positive",
        "licenses",
        type_="check",
    )
    op.drop_column("licenses", "seats_total")
    op.drop_column("licenses", "seats_used")
