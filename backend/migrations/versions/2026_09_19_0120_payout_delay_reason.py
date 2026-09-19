"""Add payouts.delay_reason so a waiting payout can say why.

A payout the platform cannot yet fund stays at `pending` and is retried
hourly until the Paystack balance recovers. That works, but it is silent: the
beneficiary sees `pending` for days, with their balance locked the whole
time, and nothing distinguishes it from a payout that is merely slow.

This column carries the reason a payout is still waiting, so the status can
be explained rather than guessed at. It is cleared the moment the transfer is
accepted, because a reason that outlives its cause is worse than none.

Revision ID: 2026_09_19_0120
Revises: 2026_09_19_0119
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_09_19_0120"
down_revision: str | Sequence[str] | None = "2026_09_19_0119"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable delay reason to payouts."""
    op.add_column(
        "payouts",
        sa.Column("delay_reason", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """Drop the delay reason."""
    op.drop_column("payouts", "delay_reason")
