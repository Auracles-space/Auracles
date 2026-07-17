"""Add attestation clarification notification types.

When an attestor asks the requestor a clarifying question, and when the
requestor answers it, each party receives a durable notification
(``attestation_clarification_requested`` / ``attestation_clarification_answered``).
Both are stored in the ``type`` column typed by ``notification_type_enum``, so
the enum must include them or the worker insert fails and the recipient's bell
stays empty.

Revision ID: 2026_07_17_0087
Revises: 2026_07_15_0086
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_07_17_0087"
down_revision: str | Sequence[str] | None = "2026_07_15_0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the clarification requested and answered notification labels."""
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
        "'attestation_clarification_requested'"
    )
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
        "'attestation_clarification_answered'"
    )


def downgrade() -> None:
    """Leave additive enum labels in place; purge rows that use them.

    Postgres cannot drop an enum value, so downgrade only removes notifications
    stored under the new labels to keep the column readable by the prior code.
    """
    op.execute(
        "DELETE FROM notifications WHERE type::text IN "
        "('attestation_clarification_requested', "
        "'attestation_clarification_answered')"
    )
