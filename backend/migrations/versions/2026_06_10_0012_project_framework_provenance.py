"""Add Project provenance to Frameworks.

Revision ID: 2026_06_10_0012
Revises: 2026_06_09_0011
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_10_0012"
down_revision: str | Sequence[str] | None = "2026_06_09_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply nullable Project provenance to contributor Framework drafts."""
    op.add_column(
        "frameworks",
        sa.Column("source_project_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_frameworks_source_project_id_projects",
        "frameworks",
        "projects",
        ["source_project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_frameworks_source_project_id",
        "frameworks",
        ["source_project_id"],
    )


def downgrade() -> None:
    """Remove Project provenance from Frameworks."""
    op.drop_index("idx_frameworks_source_project_id", table_name="frameworks")
    op.drop_constraint(
        "fk_frameworks_source_project_id_projects",
        "frameworks",
        type_="foreignkey",
    )
    op.drop_column("frameworks", "source_project_id")
