"""Add organization invitation notification types.

The invitation flow emits in-app notifications on invite creation and on
future accept/decline transitions. The enum values remain on downgrade because
Postgres cannot drop a single enum label cleanly.

Revision ID: 2026_07_03_0060
Revises: 2026_07_03_0059
Create Date: 2026-07-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_07_03_0060"
down_revision: str | Sequence[str] | None = "2026_07_03_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add notification enum values for organization invitations."""
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notification_type_enum "
            "ADD VALUE IF NOT EXISTS 'org_invitation_received'"
        )
        op.execute(
            "ALTER TYPE notification_type_enum "
            "ADD VALUE IF NOT EXISTS 'org_invitation_accepted'"
        )
        op.execute(
            "ALTER TYPE notification_type_enum "
            "ADD VALUE IF NOT EXISTS 'org_invitation_declined'"
        )


def downgrade() -> None:
    """Leave the enum values in place; Postgres cannot drop them cleanly."""
    pass
