"""Add unrecognized_transfers for out-of-band money movement.

A Paystack transfer that matches no payout or platform withdrawal used to be
acknowledged and ignored, so money moved from the Paystack dashboard left no
trace in Auracles (treasury decision 5). Each such transfer is now recorded
once per reference and kept until the super-admin marks it reviewed.

Revision ID: 2026_09_16_0114
Revises: 2026_09_16_0113
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_09_16_0114"
down_revision: str | Sequence[str] | None = "2026_09_16_0113"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the unrecognized_transfers table."""
    op.create_table(
        "unrecognized_transfers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "provider",
            postgresql.ENUM(
                "stripe", "paystack", name="payment_provider_enum", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("provider_ref", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("recipient_name", sa.String(255), nullable=True),
        sa.Column("recipient_bank", sa.String(255), nullable=True),
        sa.Column("recipient_last4", sa.String(4), nullable=True),
        sa.Column(
            "acknowledged_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
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
            "provider", "provider_ref", name="uq_unrecognized_transfers_ref"
        ),
    )
    op.create_index(
        "idx_unrecognized_transfers_unreviewed",
        "unrecognized_transfers",
        ["created_at"],
        postgresql_where=sa.text("acknowledged_at IS NULL"),
    )


def downgrade() -> None:
    """Drop the unrecognized_transfers table."""
    op.drop_index(
        "idx_unrecognized_transfers_unreviewed", table_name="unrecognized_transfers"
    )
    op.drop_table("unrecognized_transfers")
