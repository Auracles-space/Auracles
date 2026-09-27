"""Add the notification label for an artifact held in PII review.

Nothing told a contributor their artifact had been flagged. The framework
silently stopped short of publishing, their profile still counted it, and the
only trace was an admin-queue badge reading "Contributor follow-up required" —
which named neither the contributor nor where to go. QA hit exactly that and
reported the framework as missing with no button to click.

Revision ID: 2026_09_27_0122
Revises: 2026_09_23_0121
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_09_27_0122"
down_revision: str | Sequence[str] | None = "2026_09_23_0121"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LABEL = "artifact_pii_review_required"


def upgrade() -> None:
    """Add the PII-review notification label."""
    op.execute(f"ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS '{LABEL}'")


def downgrade() -> None:
    """Purge rows under the label; Postgres cannot drop an enum value."""
    op.execute(f"DELETE FROM notifications WHERE type::text = '{LABEL}'")
