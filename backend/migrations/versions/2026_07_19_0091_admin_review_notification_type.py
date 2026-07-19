"""Add admin_review_pending notification type.

Supports admin-review fan-out notifications: when a user submits work that
lands in an admin queue (developer application, credential, org-attestor
application, project dispute, attestation needing admin), every admin account
receives one durable notification instead of relying on page polling.

Revision ID: 2026_07_19_0091
Revises: 2026_07_19_0090
Create Date: 2026-07-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_07_19_0091"
down_revision: str | Sequence[str] | None = "2026_07_19_0090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the admin-review notification label."""
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
        "'admin_review_pending'"
    )


def downgrade() -> None:
    """Leave the additive enum label in place; drop only emitted rows."""
    op.execute(
        "DELETE FROM notifications WHERE type::text = 'admin_review_pending'"
    )
