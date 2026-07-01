"""Rename dispute-window config to business days and reseed the default.

Module 5 changes the dispute window from 14 calendar days to 5 business days.
The config key is renamed to make the semantics explicit and to stop a stale
calendar value from leaking in. In-flight rows keep their existing
dispute_window_ends_at timestamps (auto-release reads the timestamp, not the
config), so no data backfill is performed.

Maps to: Module 5 design spec section 4.2 / 4.9 (window migration).

Revision ID: 2026_07_01_0049
Revises: 2026_07_01_0048
Create Date: 2026-07-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_07_01_0049"
down_revision: str | Sequence[str] | None = "2026_07_01_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace the calendar-day window config row with the business-day key."""
    op.execute(
        "DELETE FROM platform_config WHERE key = 'attestation_dispute_window_days'"
    )
    op.execute(
        "INSERT INTO platform_config (key, value) "
        "VALUES ('attestation_dispute_window_business_days', '5') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    """Restore the calendar-day window config key."""
    op.execute(
        "DELETE FROM platform_config "
        "WHERE key = 'attestation_dispute_window_business_days'"
    )
    op.execute(
        "INSERT INTO platform_config (key, value) "
        "VALUES ('attestation_dispute_window_days', '14') "
        "ON CONFLICT (key) DO NOTHING"
    )
