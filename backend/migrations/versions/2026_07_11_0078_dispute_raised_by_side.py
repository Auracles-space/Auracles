"""Record which party raised a project dispute.

Adds a nullable ``raised_by_side`` to disputes so the counterparty-facing
dispute view can show the acting side ("operator" or "contributor") without
exposing the raising org member's user id. The existing ``raised_by`` column is
retained for audit, admin, and GDPR. Existing rows are backfilled by comparing
``raised_by`` against the project's individual operator.

Revision ID: 2026_07_11_0078
Revises: 2026_07_11_0077
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_11_0078"
down_revision: str | Sequence[str] | None = "2026_07_11_0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``raised_by_side`` and backfill from the individual operator."""
    op.add_column(
        "disputes",
        sa.Column("raised_by_side", sa.String(length=20), nullable=True),
    )
    # Backfill: operator-side when the raiser is the individual operator or a
    # member of the operating org; otherwise contributor-side.
    op.execute(
        """
        UPDATE disputes AS d
        SET raised_by_side = CASE
            WHEN (p.operator_id IS NOT NULL AND d.raised_by = p.operator_id)
                OR (p.operator_org_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM org_members m
                    WHERE m.org_id = p.operator_org_id
                      AND m.user_id = d.raised_by
                ))
                THEN 'operator'
            ELSE 'contributor'
        END
        FROM projects AS p
        WHERE p.id = d.project_id
        """
    )


def downgrade() -> None:
    """Drop the dispute ``raised_by_side`` column."""
    op.drop_column("disputes", "raised_by_side")
