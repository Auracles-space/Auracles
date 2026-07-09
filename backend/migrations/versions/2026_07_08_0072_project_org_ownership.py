"""Add additive organization ownership columns to Project proposals and Deliverables.

Supports Task 6 in docs/superpowers/plans/2026-07-08-org-contributor.md by
allowing a Proposal or Deliverable to belong to either an individual
Contributor or an organization through the same XOR ownership model used in
frameworks.

Revision ID: 2026_07_08_0072
Revises: 2026_07_08_0071
Create Date: 2026-07-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_08_0072"
down_revision: str | Sequence[str] | None = "2026_07_08_0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add org ownership columns and XOR constraints to proposals and Deliverables."""
    op.add_column(
        "proposals",
        sa.Column("contributor_org_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "proposals",
        sa.Column("delivering_member_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("proposals", "contributor_id", nullable=True)
    op.create_foreign_key(
        "fk_proposals_contributor_org_id",
        "proposals",
        "organizations",
        ["contributor_org_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_proposals_delivering_member_id",
        "proposals",
        "org_members",
        ["delivering_member_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_proposals_seller_xor",
        "proposals",
        "(contributor_id IS NULL) != (contributor_org_id IS NULL)",
    )
    op.create_index(
        "uq_proposals_project_org_active",
        "proposals",
        ["project_id", "contributor_org_id"],
        unique=True,
        postgresql_where=sa.text(
            "contributor_org_id IS NOT NULL AND status IN ('pending', 'accepted')"
        ),
    )

    op.add_column(
        "deliverables",
        sa.Column("contributor_org_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("deliverables", "contributor_id", nullable=True)
    op.create_foreign_key(
        "fk_deliverables_contributor_org_id",
        "deliverables",
        "organizations",
        ["contributor_org_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_deliverables_seller_xor",
        "deliverables",
        "(contributor_id IS NULL) != (contributor_org_id IS NULL)",
    )


def downgrade() -> None:
    """Remove additive org ownership columns and restore user-only ownership."""
    op.drop_constraint(
        "ck_deliverables_seller_xor",
        "deliverables",
        type_="check",
    )
    op.drop_constraint(
        "fk_deliverables_contributor_org_id",
        "deliverables",
        type_="foreignkey",
    )
    op.alter_column("deliverables", "contributor_id", nullable=False)
    op.drop_column("deliverables", "contributor_org_id")

    op.drop_index("uq_proposals_project_org_active", table_name="proposals")
    op.drop_constraint("ck_proposals_seller_xor", "proposals", type_="check")
    op.drop_constraint(
        "fk_proposals_delivering_member_id",
        "proposals",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_proposals_contributor_org_id",
        "proposals",
        type_="foreignkey",
    )
    op.alter_column("proposals", "contributor_id", nullable=False)
    op.drop_column("proposals", "delivering_member_id")
    op.drop_column("proposals", "contributor_org_id")
