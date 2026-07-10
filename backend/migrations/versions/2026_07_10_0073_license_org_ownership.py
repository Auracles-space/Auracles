"""Add additive organization ownership to licenses.

Supports Task 2 in docs/superpowers/plans/2026-07-10-org-operator.md by
allowing a License to be held by either an individual Operator or an
organization through an XOR holder model while preserving existing individual
rows.

Revision ID: 2026_07_10_0073
Revises: 2026_07_08_0072
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_10_0073"
down_revision: str | Sequence[str] | None = "2026_07_08_0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add additive org ownership columns and grant allocation to licenses."""
    op.add_column(
        "licenses",
        sa.Column("licensee_org_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("licenses", "operator_id", nullable=True)
    op.create_foreign_key(
        "fk_licenses_licensee_org_id",
        "licenses",
        "organizations",
        ["licensee_org_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_licenses_holder_xor",
        "licenses",
        "(operator_id IS NULL) != (licensee_org_id IS NULL)",
    )
    op.create_index(
        "uq_licenses_org_owner",
        "licenses",
        ["framework_id", "licensee_org_id"],
        unique=True,
        postgresql_where=sa.text("licensee_org_id IS NOT NULL"),
    )
    op.create_index("idx_licenses_org", "licenses", ["licensee_org_id"])

    op.create_table(
        "license_grants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("license_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "(team_id IS NULL) != (member_id IS NULL)",
            name="ck_license_grants_target_xor",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["org_members.id"],
            name="fk_license_grants_granted_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["license_id"],
            ["licenses.id"],
            name="fk_license_grants_license_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["org_members.id"],
            name="fk_license_grants_member_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["org_teams.id"],
            name="fk_license_grants_team_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_license_grants")),
    )
    op.create_index(
        "uq_license_grants_team",
        "license_grants",
        ["license_id", "team_id"],
        unique=True,
        postgresql_where=sa.text("team_id IS NOT NULL"),
    )
    op.create_index(
        "uq_license_grants_member",
        "license_grants",
        ["license_id", "member_id"],
        unique=True,
        postgresql_where=sa.text("member_id IS NOT NULL"),
    )
    op.create_index(
        "idx_license_grants_member",
        "license_grants",
        ["member_id"],
    )
    op.create_index(
        "idx_license_grants_team",
        "license_grants",
        ["team_id"],
    )


def downgrade() -> None:
    """Remove additive org ownership columns and restore user-only ownership.

    This downgrade restores the pre-org dev schema and assumes no org-owned
    license rows remain when `operator_id` is tightened back to NOT NULL.
    """

    op.execute("DROP INDEX IF EXISTS idx_license_grants_team")
    op.execute("DROP INDEX IF EXISTS idx_license_grants_member")
    op.execute("DROP INDEX IF EXISTS uq_license_grants_member")
    op.execute("DROP INDEX IF EXISTS uq_license_grants_team")
    op.execute("DROP TABLE IF EXISTS license_grants")

    op.execute("DROP INDEX IF EXISTS idx_licenses_org")
    op.execute("DROP INDEX IF EXISTS uq_licenses_org_owner")
    op.execute(
        "ALTER TABLE licenses DROP CONSTRAINT IF EXISTS ck_licenses_holder_xor"
    )
    op.execute(
        "ALTER TABLE licenses DROP CONSTRAINT IF EXISTS fk_licenses_licensee_org_id"
    )
    op.alter_column("licenses", "operator_id", nullable=False)
    op.drop_column("licenses", "licensee_org_id")
