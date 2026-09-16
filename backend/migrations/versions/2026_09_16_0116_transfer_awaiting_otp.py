"""Add awaiting_otp to platform_withdrawals and payouts.

When transfer OTP is switched on for the Paystack account, every transfer
stops at status ``otp`` and no webhook follows until someone enters the code.
A withdrawal or payout in that state looked like an ordinary "processing"
one. The flag lets the admin Treasury and Payouts pages say it is waiting for
an OTP.

Revision ID: 2026_09_16_0116
Revises: 2026_09_16_0115
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_09_16_0116"
down_revision: str | Sequence[str] | None = "2026_09_16_0115"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLES = ("platform_withdrawals", "payouts")


def upgrade() -> None:
    """Add the awaiting_otp flag, false for existing rows."""
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "awaiting_otp",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )


def downgrade() -> None:
    """Drop the awaiting_otp flag."""
    for table in TABLES:
        op.drop_column(table, "awaiting_otp")
