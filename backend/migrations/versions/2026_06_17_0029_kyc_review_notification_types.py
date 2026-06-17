"""Add KYC review notification types.

Lets the admin KYC review create a durable user notification when an
identity document is verified or rejected, so the user learns the outcome
of the asynchronous review without polling the status page.

Revision ID: 2026_06_17_0029
Revises: 2026_06_15_0028
Create Date: 2026-06-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_06_17_0029"
down_revision: str | Sequence[str] | None = "2026_06_15_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the KYC verified/rejected notification labels."""
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS 'kyc_verified'"
    )
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS 'kyc_rejected'"
    )


def downgrade() -> None:
    """Remove KYC notifications; the additive enum labels stay in place."""
    op.execute(
        "DELETE FROM notifications WHERE type::text IN ('kyc_verified', 'kyc_rejected')"
    )
