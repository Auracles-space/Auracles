"""Add notification labels for an individual payee's payout outcome.

An Organization heard when its payout was requested, completed or failed. A
person paid directly heard nothing at any stage — outcome notices were gated on
`payout.org_id is not None`, and the one individual label that existed covered
only a failed Stripe bank payout. On Paystack, the pilot's own rail, a payout
can settle, defer for hours, or be abandoned entirely, and the payee had no way
to learn which.

QA found it by requesting a payout on an individual account and seeing nothing.

Revision ID: 2026_09_29_0124
Revises: 2026_09_28_0123
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_09_29_0124"
down_revision: str | Sequence[str] | None = "2026_09_28_0123"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LABEL = "payout_completed"


def upgrade() -> None:
    """Add the completed-payout label for individual payees.

    `payout_failed` already exists and is reused rather than duplicated: the
    failure notice becomes rail-agnostic in application code instead of
    gaining a second label that means the same thing.
    """
    op.execute(f"ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS '{LABEL}'")


def downgrade() -> None:
    """Purge rows under the label; Postgres cannot drop an enum value."""
    op.execute(f"DELETE FROM notifications WHERE type::text = '{LABEL}'")
