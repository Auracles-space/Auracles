"""Add platform_withdrawals and the platform withdrawal minimum.

The platform withdraws its own money from the Paystack balance to its bank
account (treasury decisions 4, 8 and 10). A partial unique index allows only
one pending or processing withdrawal per currency, and the ₦10,000 minimum is
seeded as super-admin-editable configuration.

Revision ID: 2026_09_16_0113
Revises: 2026_09_16_0112
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_09_16_0113"
down_revision: str | Sequence[str] | None = "2026_09_16_0112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MINIMUM_KEY = "min_platform_withdrawal_ngn"
MINIMUM_VALUE = "10000.00"


def upgrade() -> None:
    """Create platform_withdrawals and seed the withdrawal minimum."""
    op.create_table(
        "platform_withdrawals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "bank_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_bank_accounts.id"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("provider_ref", sa.String(255), nullable=False, unique=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "requested_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "amount > 0", name="ck_platform_withdrawals_amount_positive"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_platform_withdrawals_status",
        ),
    )
    op.create_index(
        "uq_platform_withdrawals_one_in_flight",
        "platform_withdrawals",
        ["currency"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )
    op.create_index(
        "idx_platform_withdrawals_requested_at",
        "platform_withdrawals",
        ["requested_at"],
    )
    op.get_bind().execute(
        sa.text(
            "INSERT INTO platform_config (key, value) VALUES (:key, :value) "
            "ON CONFLICT (key) DO NOTHING"
        ).bindparams(key=MINIMUM_KEY, value=MINIMUM_VALUE)
    )


def downgrade() -> None:
    """Drop platform_withdrawals and the withdrawal minimum."""
    op.get_bind().execute(
        sa.text("DELETE FROM platform_config WHERE key = :key").bindparams(
            key=MINIMUM_KEY
        )
    )
    op.drop_index(
        "idx_platform_withdrawals_requested_at", table_name="platform_withdrawals"
    )
    op.drop_index(
        "uq_platform_withdrawals_one_in_flight", table_name="platform_withdrawals"
    )
    op.drop_table("platform_withdrawals")
