"""Add provider_fees for platform treasury cost tracking.

The platform absorbs Paystack's fee on every charge and transfer (treasury
decision 6), but no fee was stored anywhere, so the platform's earnings were
overstated. Fees get their own append-only table (decision 12) rather than a
column on transactions, because transfers and platform withdrawals carry fees
too and a charge can be paid more than once.

Revision ID: 2026_09_16_0111
Revises: 2026_09_15_0110
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_09_16_0111"
down_revision: str | Sequence[str] | None = "2026_09_15_0110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the provider_fees table and its indexes."""
    op.create_table(
        "provider_fees",
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
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("provider_ref", sa.String(255), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("amount > 0", name="ck_provider_fees_amount_positive"),
        sa.CheckConstraint(
            "source_type IN ('transaction', 'payout', 'partner_payout', "
            "'platform_withdrawal')",
            name="ck_provider_fees_source_type",
        ),
        sa.CheckConstraint(
            "origin IN ('webhook', 'backfill')", name="ck_provider_fees_origin"
        ),
        sa.UniqueConstraint(
            "provider",
            "source_type",
            "provider_ref",
            name="uq_provider_fees_provider_source_ref",
        ),
    )
    op.create_index(
        "idx_provider_fees_source", "provider_fees", ["source_type", "source_id"]
    )
    op.create_index(
        "idx_provider_fees_currency_occurred_at",
        "provider_fees",
        ["currency", "occurred_at"],
    )


def downgrade() -> None:
    """Drop the provider_fees table."""
    op.drop_index("idx_provider_fees_currency_occurred_at", table_name="provider_fees")
    op.drop_index("idx_provider_fees_source", table_name="provider_fees")
    op.drop_table("provider_fees")
