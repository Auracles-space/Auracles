"""Add org attestor approval and rejection notification types.

When an admin decides an org attestor application, the org owners must be
told the outcome: ``org_attestor_approved`` on activation and
``org_attestor_rejected`` on a terminal rejection. Both are stored in the
``type`` column typed by ``notification_type_enum``, so the enum must include
them or the worker insert fails and the owner is never told.

Revision ID: 2026_07_15_0086
Revises: 2026_07_15_0085
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_07_15_0086"
down_revision: str | Sequence[str] | None = "2026_07_15_0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the approval and rejection notification labels."""
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
        "'org_attestor_approved'"
    )
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
        "'org_attestor_rejected'"
    )


def downgrade() -> None:
    """Leave additive enum labels in place; purge rows that use them.

    Postgres cannot drop an enum value, so downgrade only removes notifications
    stored under the new labels to keep the column readable by the prior code.
    """
    op.execute(
        "DELETE FROM notifications WHERE type::text IN "
        "('org_attestor_approved', 'org_attestor_rejected')"
    )
