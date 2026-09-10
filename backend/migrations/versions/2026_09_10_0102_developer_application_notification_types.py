"""Add Developer application decision notification types.

The admin review of a Developer Platform application wrote its decision and
audit row but told the applicant nothing, so approval and rejection were both
silent. Delivering that verdict needs labels the notification enum does not
carry yet.

Revision ID: 2026_09_10_0102
Revises: 2026_09_10_0101
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_09_10_0102"
down_revision: str | Sequence[str] | None = "2026_09_10_0101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the Developer application approved and rejected labels."""
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
        "'developer_application_approved'"
    )
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
        "'developer_application_rejected'"
    )


def downgrade() -> None:
    """Drop notifications using the new labels; the labels themselves stay.

    Postgres cannot remove a value from an enum in place, and every other
    notification-type migration here takes the same additive-only approach.
    """
    op.execute(
        "DELETE FROM notifications WHERE type::text IN "
        "('developer_application_approved', 'developer_application_rejected')"
    )
