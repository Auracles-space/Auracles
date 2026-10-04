"""Add the three account-deletion notification types.

Requesting account deletion notified admins and nobody else, so the person
whose account was about to be erased received no acknowledgement, no date, and
no mention of the cooling-off window they could cancel within. These three
labels carry that acknowledgement, and the scheduled one doubles as the
out-of-band warning if someone other than the account holder started it.

Revision ID: 2026_10_04_0126
Revises: 2026_10_03_0125
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_10_04_0126"
down_revision: str | Sequence[str] | None = "2026_10_03_0125"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = (
    "account_deletion_scheduled",
    "account_deletion_blocked",
    "account_deletion_cancelled",
)


def upgrade() -> None:
    """Add the account-deletion notification labels."""
    for label in _TYPES:
        op.execute(
            f"ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS '{label}'"
        )


def downgrade() -> None:
    """Leave the additive enum labels in place; drop only emitted rows."""
    labels = ", ".join(f"'{label}'" for label in _TYPES)
    op.execute(f"DELETE FROM notifications WHERE type::text IN ({labels})")
    # notifications stores the enum in a column named `type`; preferences
    # names the same enum `notification_type`.
    op.execute(
        "DELETE FROM notification_preferences "
        f"WHERE notification_type::text IN ({labels})"
    )
