"""Add the org attestor needs-info notification type.

When an admin sends an org attestor application back for changes, the org
owners must receive a durable notification (``org_attestor_needs_info``) so
they know work is required. The label is stored in the ``type`` column typed
by ``notification_type_enum``, so the enum must include it or the worker
insert fails and the owner is never told.

Revision ID: 2026_07_15_0085
Revises: 2026_07_15_0084
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_07_15_0085"
down_revision: str | Sequence[str] | None = "2026_07_15_0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the needs-info notification label."""
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
        "'org_attestor_needs_info'"
    )


def downgrade() -> None:
    """Leave the additive enum label in place; purge rows that use it.

    Postgres cannot drop an enum value, so downgrade only removes notifications
    stored under the new label to keep the column readable by the prior code.
    """
    op.execute(
        "DELETE FROM notifications WHERE type::text = 'org_attestor_needs_info'"
    )
