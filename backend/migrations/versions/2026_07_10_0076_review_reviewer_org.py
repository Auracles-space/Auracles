"""Add additive organization reviewer identity to framework reviews.

Supports Task 8 in docs/superpowers/specs/2026-07-10-org-operator-design.md by
allowing a review to be authored by either an individual Operator or an
organization through an XOR reviewer model, while preserving every existing
individual-authored review row. The ``reviewing_member_id`` records which org
member authored the review internally and is never exposed on public response
schemas.

Revision ID: 2026_07_10_0076
Revises: 2026_07_10_0075
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_10_0076"
down_revision: str | Sequence[str] | None = "2026_07_10_0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add org reviewer columns, XOR constraint, and org uniqueness."""
    op.add_column(
        "reviews",
        sa.Column("reviewer_org_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "reviews",
        sa.Column("reviewing_member_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("reviews", "operator_id", nullable=True)
    op.create_foreign_key(
        "fk_reviews_reviewer_org_id",
        "reviews",
        "organizations",
        ["reviewer_org_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_reviews_reviewing_member_id",
        "reviews",
        "org_members",
        ["reviewing_member_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_reviews_reviewer_xor",
        "reviews",
        "(operator_id IS NULL) != (reviewer_org_id IS NULL)",
    )
    op.create_index(
        "uq_reviews_framework_reviewer_org",
        "reviews",
        ["framework_id", "reviewer_org_id"],
        unique=True,
        postgresql_where=sa.text("reviewer_org_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove additive org reviewer identity and restore user-only reviews.

    This downgrade restores the pre-org-review dev schema and assumes no
    org-authored Review rows remain when ``operator_id`` is tightened back to
    NOT NULL.
    """
    op.execute("DROP INDEX IF EXISTS uq_reviews_framework_reviewer_org")
    op.execute("ALTER TABLE reviews DROP CONSTRAINT IF EXISTS ck_reviews_reviewer_xor")
    op.execute(
        "ALTER TABLE reviews DROP CONSTRAINT IF EXISTS fk_reviews_reviewing_member_id"
    )
    op.execute(
        "ALTER TABLE reviews DROP CONSTRAINT IF EXISTS fk_reviews_reviewer_org_id"
    )
    op.alter_column("reviews", "operator_id", nullable=False)
    op.drop_column("reviews", "reviewing_member_id")
    op.drop_column("reviews", "reviewer_org_id")
