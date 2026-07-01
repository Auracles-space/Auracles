"""Restructure dispute resolution: outcome enum, drop split, add revision fields.

[HUMAN REVIEW REQUIRED]: This migration drops shipped columns (resolution_type,
release_amount, refund_amount) and the constraint
ck_attestation_disputes_split_has_amounts from attestation_disputes. The 'split'
resolution type has been deliberately removed from the product design per the
Module 5 spec.

Downgrade note: The 'revision_requested' value added to attestation_status_enum
cannot be removed on downgrade — Postgres does not support removing enum values.
Leaving it is harmless; rows using it will have been cleaned up by rollback logic.

Maps to: Module 5 design spec section 4.6 (outcome restructure).

Revision ID: 2026_07_01_0052
Revises: 2026_07_01_0051
Create Date: 2026-07-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_01_0052"
down_revision: str | Sequence[str] | None = "2026_07_01_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add outcome enum, revision fields; drop split columns and enum type."""
    # 1. Add revision_requested to attestation_status_enum.
    # Must run inside an autocommit block — ALTER TYPE ... ADD VALUE cannot
    # run inside a transaction in Postgres.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE attestation_status_enum "
            "ADD VALUE IF NOT EXISTS 'revision_requested' "
            "AFTER 'report_submitted'"
        )

    # 2. Create the new outcome enum type.
    outcome_enum = postgresql.ENUM(
        "rejected",
        "upheld_refund",
        "upheld_revise",
        name="attestation_dispute_outcome_enum",
        create_type=False,
    )
    outcome_enum.create(op.get_bind(), checkfirst=True)

    # 3. Add new columns to attestation_disputes.
    op.add_column(
        "attestation_disputes",
        sa.Column("outcome", outcome_enum, nullable=True),
    )
    op.add_column(
        "attestation_disputes",
        sa.Column(
            "is_complex",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "attestation_disputes",
        sa.Column("resolution_due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attestation_disputes",
        sa.Column("resolution_overdue_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 4. Add new columns to attestations.
    op.add_column(
        "attestations",
        sa.Column(
            "revision_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "attestations",
        sa.Column(
            "report_published_eligible",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    # 5. Drop the split constraint and old columns from attestation_disputes.
    # Constraint must be dropped before columns that referenced it.
    op.drop_constraint(
        "ck_attestation_disputes_split_has_amounts",
        "attestation_disputes",
        type_="check",
    )
    op.drop_column("attestation_disputes", "resolution_type")
    op.drop_column("attestation_disputes", "release_amount")
    op.drop_column("attestation_disputes", "refund_amount")

    # 6. Drop the old resolution enum type.
    op.execute("DROP TYPE IF EXISTS attestation_dispute_resolution_enum")


def downgrade() -> None:
    """Re-create old split columns/enum; drop new outcome columns/enum.

    Note: 'revision_requested' added to attestation_status_enum cannot be
    removed — Postgres limitation. Leaving it is harmless.
    """
    # 1. Re-create the old resolution enum type.
    resolution_enum = postgresql.ENUM(
        "release",
        "refund",
        "split",
        name="attestation_dispute_resolution_enum",
        create_type=False,
    )
    resolution_enum.create(op.get_bind(), checkfirst=True)

    # 2. Re-add old columns to attestation_disputes.
    op.add_column(
        "attestation_disputes",
        sa.Column("resolution_type", resolution_enum, nullable=True),
    )
    op.add_column(
        "attestation_disputes",
        sa.Column("release_amount", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "attestation_disputes",
        sa.Column("refund_amount", sa.Numeric(12, 2), nullable=True),
    )

    # 3. Re-create the split constraint.
    op.create_check_constraint(
        "ck_attestation_disputes_split_has_amounts",
        "attestation_disputes",
        "resolution_type != 'split' "
        "OR (release_amount IS NOT NULL AND refund_amount IS NOT NULL)",
    )

    # 4. Drop new attestation columns.
    op.drop_column("attestations", "report_published_eligible")
    op.drop_column("attestations", "revision_count")

    # 5. Drop new dispute columns.
    op.drop_column("attestation_disputes", "resolution_overdue_at")
    op.drop_column("attestation_disputes", "resolution_due_at")
    op.drop_column("attestation_disputes", "is_complex")
    op.drop_column("attestation_disputes", "outcome")

    # 6. Drop the outcome enum type.
    op.execute("DROP TYPE IF EXISTS attestation_dispute_outcome_enum")
