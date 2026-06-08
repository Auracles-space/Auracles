"""Add Framework version Artifact snapshot table.

Revision ID: 2026_06_08_0007
Revises: 2026_06_07_0006
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_08_0007"
down_revision: str | Sequence[str] | None = "2026_06_07_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create version snapshots and current Artifact membership support."""
    op.add_column(
        "artifacts",
        sa.Column(
            "current_for_framework",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.create_index(
        "idx_artifacts_current_framework",
        "artifacts",
        ["framework_id", "current_for_framework"],
    )
    op.create_table(
        "framework_version_artifacts",
        sa.Column(
            "framework_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "is_preview",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.ForeignKeyConstraint(
            ["framework_version_id"],
            ["framework_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.PrimaryKeyConstraint(
            "framework_version_id",
            "artifact_id",
            name="pk_framework_version_artifacts",
        ),
    )
    op.create_index(
        "idx_framework_version_artifacts_artifact",
        "framework_version_artifacts",
        ["artifact_id"],
    )


def downgrade() -> None:
    """Remove version snapshots and current Artifact membership support."""
    op.drop_index(
        "idx_framework_version_artifacts_artifact",
        table_name="framework_version_artifacts",
    )
    op.drop_table("framework_version_artifacts")
    op.execute("DROP INDEX IF EXISTS idx_artifacts_current_framework")
    op.execute("ALTER TABLE artifacts DROP COLUMN IF EXISTS current_for_framework")
