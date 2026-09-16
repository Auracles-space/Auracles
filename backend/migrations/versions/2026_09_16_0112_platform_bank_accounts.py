"""Add platform_bank_accounts for treasury withdrawals.

The platform needs a destination for its own money (treasury decision 3).
Changes are append-only so the history of destinations is never lost, one
active row is enforced by a partial unique index, and only the encrypted
Paystack recipient code plus display-safe fields are stored.

Revision ID: 2026_09_16_0112
Revises: 2026_09_16_0111
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_09_16_0112"
down_revision: str | Sequence[str] | None = "2026_09_16_0111"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the platform_bank_accounts table and its active-row index."""
    op.create_table(
        "platform_bank_accounts",
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
        sa.Column("bank_code", sa.String(20), nullable=False),
        sa.Column("bank_name", sa.String(255), nullable=False),
        sa.Column("account_last4", sa.String(4), nullable=False),
        sa.Column("account_name", sa.String(255), nullable=True),
        sa.Column("recipient_code_encrypted", sa.Text(), nullable=False),
        sa.Column("usable_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "account_last4 ~ '^[0-9]{4}$'",
            name="ck_platform_bank_accounts_last4_digits",
        ),
    )
    op.create_index(
        "uq_platform_bank_accounts_active",
        "platform_bank_accounts",
        [sa.text("(replaced_at IS NULL)")],
        unique=True,
        postgresql_where=sa.text("replaced_at IS NULL"),
    )


def downgrade() -> None:
    """Drop the platform_bank_accounts table."""
    op.drop_index(
        "uq_platform_bank_accounts_active", table_name="platform_bank_accounts"
    )
    op.drop_table("platform_bank_accounts")
