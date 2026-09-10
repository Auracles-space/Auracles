"""Add notification labels for the org business-verification verdict.

Supports DESIGN-1. An admin's KYB decision unlocks (or blocks) everything an
organization can do, and the verification screen tells the owner "we will let
you know" — so the verdict must actually be delivered rather than only
audited. Mirrors the individual KYC verdict labels.

Revision ID: 2026_09_10_0101
Revises: 2026_09_09_0100
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_09_10_0101"
down_revision: str | Sequence[str] | None = "2026_09_09_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the org KYB verified/rejected notification labels."""
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
        "'org_kyb_verified'"
    )
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
        "'org_kyb_rejected'"
    )


def downgrade() -> None:
    """Leave additive enum labels in place; purge rows that use them.

    Postgres cannot drop an enum value, so downgrade only removes notifications
    stored under the new labels to keep the column readable by the prior code.
    """
    op.execute(
        "DELETE FROM notifications WHERE type::text IN "
        "('org_kyb_verified', 'org_kyb_rejected')"
    )
