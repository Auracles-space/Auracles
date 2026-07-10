"""Add additive organization operator ownership to projects.

Supports Task 6 in docs/superpowers/specs/2026-07-10-org-operator-design.md by
allowing a Project to be operated by either an individual Operator or an
organization through an XOR ownership model, while preserving every existing
individual-operated Project row. The ``posting_member_id`` records which
organization member posted an org-operated Project for internal provenance and
is never exposed on public or Contributor-facing responses.

Revision ID: 2026_07_10_0075
Revises: 2026_07_10_0074
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_10_0075"
down_revision: str | Sequence[str] | None = "2026_07_10_0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add org operator columns, XOR constraint, and org-status index."""
    op.add_column(
        "projects",
        sa.Column("operator_org_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("posting_member_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("projects", "operator_id", nullable=True)
    op.create_foreign_key(
        "fk_projects_operator_org_id",
        "projects",
        "organizations",
        ["operator_org_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_projects_posting_member_id",
        "projects",
        "org_members",
        ["posting_member_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_projects_operator_xor",
        "projects",
        "(operator_id IS NULL) != (operator_org_id IS NULL)",
    )
    op.create_index(
        "idx_projects_operator_org_status",
        "projects",
        ["operator_org_id", "status"],
    )


def downgrade() -> None:
    """Remove additive org operator columns and restore user-only ownership.

    This downgrade restores the pre-org-operator dev schema and assumes no
    org-operated Project rows remain when ``operator_id`` is tightened back to
    NOT NULL.
    """
    op.execute("DROP INDEX IF EXISTS idx_projects_operator_org_status")
    op.execute(
        "ALTER TABLE projects DROP CONSTRAINT IF EXISTS ck_projects_operator_xor"
    )
    op.execute(
        "ALTER TABLE projects DROP CONSTRAINT IF EXISTS fk_projects_posting_member_id"
    )
    op.execute(
        "ALTER TABLE projects DROP CONSTRAINT IF EXISTS fk_projects_operator_org_id"
    )
    op.alter_column("projects", "operator_id", nullable=False)
    op.drop_column("projects", "posting_member_id")
    op.drop_column("projects", "operator_org_id")
