"""Add additive organization ownership columns to frameworks.

Supports Task 2 in docs/superpowers/plans/2026-07-08-org-contributor.md by
allowing a Framework to be owned by either an individual Contributor or an
organization through an XOR seller model while preserving existing individual
rows.

Revision ID: 2026_07_08_0071
Revises: 2026_07_08_0070
Create Date: 2026-07-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_08_0071"
down_revision: str | Sequence[str] | None = "2026_07_08_0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add additive org ownership columns and XOR enforcement to frameworks."""
    op.add_column(
        "frameworks",
        sa.Column("contributor_org_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "frameworks",
        sa.Column("authoring_member_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("frameworks", "contributor_id", nullable=True)
    op.create_foreign_key(
        "fk_frameworks_contributor_org_id",
        "frameworks",
        "organizations",
        ["contributor_org_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_frameworks_authoring_member_id",
        "frameworks",
        "org_members",
        ["authoring_member_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_frameworks_contributor_org_status",
        "frameworks",
        ["contributor_org_id", "status"],
    )
    op.create_check_constraint(
        "ck_frameworks_seller_xor",
        "frameworks",
        "(contributor_id IS NULL) != (contributor_org_id IS NULL)",
    )


def downgrade() -> None:
    """Remove additive org ownership columns and restore user-only ownership."""
    op.drop_constraint("ck_frameworks_seller_xor", "frameworks", type_="check")
    op.drop_index("idx_frameworks_contributor_org_status", table_name="frameworks")
    op.drop_constraint(
        "fk_frameworks_authoring_member_id",
        "frameworks",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_frameworks_contributor_org_id",
        "frameworks",
        type_="foreignkey",
    )
    op.alter_column("frameworks", "contributor_id", nullable=False)
    op.drop_column("frameworks", "authoring_member_id")
    op.drop_column("frameworks", "contributor_org_id")
