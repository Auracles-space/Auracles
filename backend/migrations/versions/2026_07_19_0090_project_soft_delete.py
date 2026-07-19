"""Add a soft-delete marker to Projects.

Project records can carry proposals, workspace history, and financial audit
references that must not be destroyed by a user-facing delete action. A
nullable marker hides eligible uncommenced Projects while retaining that
history. Existing rows remain active because the column has no default.

Revision ID: 2026_07_19_0090
Revises: 2026_07_17_0089
Create Date: 2026-07-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_19_0090"
down_revision: str | Sequence[str] | None = "2026_07_17_0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable Project deletion timestamp."""
    op.add_column(
        "projects",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove the Project deletion timestamp."""
    op.drop_column("projects", "deleted_at")
