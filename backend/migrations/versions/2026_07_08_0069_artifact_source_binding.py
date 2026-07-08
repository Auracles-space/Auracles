"""Add source-binding columns to artifacts for Connectors Phase B.

Supports the draft source-preview binding described in
docs/superpowers/plans/2026-07-08-connectors-phase-b.md, Task 1. Existing
artifact rows remain valid by defaulting to ``source_kind='upload'`` so legacy
uploads and Phase A imports keep their prior behavior until a future re-bind.

Revision ID: 2026_07_08_0069
Revises: 2026_07_06_0068
Create Date: 2026-07-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_08_0069"
down_revision: str | Sequence[str] | None = "2026_07_06_0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add additive source-binding columns to artifacts."""
    op.add_column(
        "artifacts",
        sa.Column(
            "source_kind",
            sa.String(length=20),
            nullable=False,
            server_default="upload",
        ),
    )
    op.add_column(
        "artifacts",
        sa.Column("source_external_id", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "artifacts",
        sa.Column(
            "source_connection_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "artifacts",
        sa.Column("source_last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "artifacts",
        sa.Column("source_synced_revision", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_artifacts_source_connection_id",
        "artifacts",
        "oauth_connections",
        ["source_connection_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Remove the additive source-binding columns from artifacts."""
    op.drop_constraint(
        "fk_artifacts_source_connection_id",
        "artifacts",
        type_="foreignkey",
    )
    op.drop_column("artifacts", "source_synced_revision")
    op.drop_column("artifacts", "source_last_synced_at")
    op.drop_column("artifacts", "source_connection_id")
    op.drop_column("artifacts", "source_external_id")
    op.drop_column("artifacts", "source_kind")
