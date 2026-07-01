"""Add attestation_ratings table.

Revision ID: 2026_07_01_0050
Revises: 2026_07_01_0049
Create Date: 2026-07-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_01_0050"
down_revision: str | Sequence[str] | None = "2026_07_01_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the attestation_ratings table."""
    op.create_table(
        "attestation_ratings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "attestation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "rated_by",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "stars BETWEEN 1 AND 5", name="ck_attestation_ratings_stars_range"
        ),
        sa.ForeignKeyConstraint(
            ["attestation_id"],
            ["attestations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rated_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attestation_id", name="uq_attestation_ratings_attestation"
        ),
    )


def downgrade() -> None:
    """Drop the attestation_ratings table."""
    op.drop_table("attestation_ratings")
