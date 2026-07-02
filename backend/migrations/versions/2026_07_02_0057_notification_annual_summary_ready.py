"""Add annual attestation-summary notification type.

Annual earnings summaries dispatch a durable in-app/email notification when the
prior-year PDF is ready. This adds the required enum label to the shared
notification type registry.

Revision ID: 2026_07_02_0057
Revises: 2026_07_02_0056
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_07_02_0057"
down_revision: str | Sequence[str] | None = "2026_07_02_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the annual summary notification type enum value."""
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notification_type_enum "
            "ADD VALUE IF NOT EXISTS 'attestation_annual_summary_ready'"
        )


def downgrade() -> None:
    """Leave the enum value in place; Postgres cannot drop it cleanly."""
    pass
