"""Add attestor_warnings table and profile suspension-review flag.

Module 5 spec section 4.7: every upheld dispute records a formal attestor
warning. Two warnings inside a rolling 12 months flag the attestor's profile
for human suspension review (``suspension_review_at``) — never an automatic
deactivation.

Maps to: Module 5 design spec section 4.7 (warnings + suspension review).

Revision ID: 2026_07_01_0053
Revises: 2026_07_01_0052
Create Date: 2026-07-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_01_0053"
down_revision: str | Sequence[str] | None = "2026_07_01_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the attestor_warnings table and add suspension_review_at."""
    op.create_table(
        "attestor_warnings",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "attestor_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "dispute_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["attestor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["dispute_id"], ["attestation_disputes.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_attestor_warnings_attestor_created",
        "attestor_warnings",
        ["attestor_id", "created_at"],
    )
    op.add_column(
        "attestor_profiles",
        sa.Column("suspension_review_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Drop the suspension-review flag and the attestor_warnings table."""
    op.drop_column("attestor_profiles", "suspension_review_at")
    op.drop_index(
        "idx_attestor_warnings_attestor_created", table_name="attestor_warnings"
    )
    op.drop_table("attestor_warnings")
