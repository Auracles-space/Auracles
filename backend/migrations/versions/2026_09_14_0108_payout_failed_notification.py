"""Add the payout_failed notification label for individual payees.

A Stripe ``payout.failed`` means the connected account's own bank payout
failed and the money sits in that account's Stripe balance. Organizations are
told through ``org_payout_failed``; individual contributors had no label, so
they were never told at all. The downgrade purges rows of the label; the enum
value itself stays because Postgres cannot remove one.

Revision ID: 2026_09_14_0108
Revises: 2026_09_14_0107
Create Date: 2026-09-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_09_14_0108"
down_revision: str | Sequence[str] | None = "2026_09_14_0107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_LABEL = "payout_failed"


def upgrade() -> None:
    """Add the notification enum label."""
    op.execute(
        f"ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS '{NEW_LABEL}'"
    )


def downgrade() -> None:
    """Remove notifications of the label; the enum value itself stays."""
    op.execute(f"DELETE FROM notifications WHERE type::text = '{NEW_LABEL}'")
