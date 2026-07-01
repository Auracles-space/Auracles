"""Add attestation dispute category enum and abuse index.

Revision ID: 2026_07_01_0051
Revises: 2026_07_01_0050
Create Date: 2026-07-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_01_0051"
down_revision: str | Sequence[str] | None = "2026_07_01_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    category_enum = postgresql.ENUM(
        "scope_error",
        "process_violation",
        "material_inaccuracy",
        "conflict_of_interest",
        name="attestation_dispute_category_enum",
        create_type=False,
    )
    category_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "attestation_disputes",
        sa.Column(
            "category",
            category_enum,
            nullable=True,
        ),
    )

    op.execute(
        "UPDATE attestation_disputes SET category = 'material_inaccuracy' "
        "WHERE category IS NULL"
    )

    op.alter_column(
        "attestation_disputes",
        "category",
        nullable=False,
    )

    op.create_index(
        "idx_attestation_disputes_raised_by_status_resolved",
        "attestation_disputes",
        ["raised_by", "status", "resolved_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_attestation_disputes_raised_by_status_resolved",
        table_name="attestation_disputes",
    )
    op.drop_column("attestation_disputes", "category")
    op.execute("DROP TYPE attestation_dispute_category_enum")
