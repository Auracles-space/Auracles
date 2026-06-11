"""Add durable near-duplicate rarity override state.

Supports post-Phase-4 marketplace polish Slice 2 by making admin overrides of
near-duplicate hard blocks deterministic across future pipeline re-evaluations.

Revision ID: 2026_06_11_0016
Revises: 2026_06_10_0015
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_11_0016"
down_revision: str | Sequence[str] | None = "2026_06_10_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist admin near-duplicate override decisions on rarity audits."""
    op.add_column(
        "artifact_rarity_audit",
        sa.Column(
            "near_duplicate_overridden_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "artifact_rarity_audit",
        sa.Column(
            "near_duplicate_overridden_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "artifact_rarity_audit",
        sa.Column("near_duplicate_override_reason", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_artifact_rarity_audit_near_duplicate_overridden_by_users",
        "artifact_rarity_audit",
        "users",
        ["near_duplicate_overridden_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Remove near-duplicate override metadata from rarity audits."""
    op.drop_constraint(
        "fk_artifact_rarity_audit_near_duplicate_overridden_by_users",
        "artifact_rarity_audit",
        type_="foreignkey",
    )
    op.drop_column("artifact_rarity_audit", "near_duplicate_override_reason")
    op.drop_column("artifact_rarity_audit", "near_duplicate_overridden_by")
    op.drop_column("artifact_rarity_audit", "near_duplicate_overridden_at")
