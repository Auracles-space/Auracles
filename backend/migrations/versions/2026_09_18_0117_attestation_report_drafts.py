"""Add attestation_report_drafts for unfinished attestor reports.

The final report is written across sittings and runs to hundreds of words,
but its fields lived only in the reviewer's browser: any refresh threw the
work away. Drafts are saved as the reviewer types, kept private to the member
who wrote them, and removed once the report is submitted.

Revision ID: 2026_09_18_0117
Revises: 2026_09_16_0116
Create Date: 2026-09-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_09_18_0117"
down_revision: str | Sequence[str] | None = "2026_09_16_0116"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the per-reviewer report draft table."""
    op.create_table(
        "attestation_report_drafts",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "attestation_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("scope", sa.Text(), nullable=False, server_default=""),
        sa.Column("conditions", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "attestation_id",
            "user_id",
            name="uq_attestation_report_drafts_attestation_user",
        ),
    )


def downgrade() -> None:
    """Drop the report draft table."""
    op.drop_table("attestation_report_drafts")
