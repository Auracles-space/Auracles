"""Enforce one submitted Attestor application per user at the DB level.

The original partial unique index keyed on ``status = 'pending'`` became a dead
predicate once migration 2026_06_29_0041 remapped legacy ``pending`` rows to
``submitted`` and the onboarding flow stopped writing ``pending``. That left the
"one open application per user" rule guarded only by a non-locking service-layer
SELECT, which two concurrent submits can both pass. Replace the dead index with a
partial unique index on ``status = 'submitted'`` so the database enforces the
invariant; the service converts the resulting IntegrityError to HTTP 409.

Revision ID: 2026_06_29_0043
Revises: 2026_06_29_0042
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "2026_06_29_0043"
down_revision: str | Sequence[str] | None = "2026_06_29_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Swap the dead pending unique index for a submitted one."""
    op.drop_index(
        "uq_attestor_applications_user_pending",
        table_name="attestor_applications",
    )
    op.create_index(
        "uq_attestor_applications_user_submitted",
        "attestor_applications",
        ["user_id"],
        unique=True,
        postgresql_where=text("status = 'submitted'"),
    )


def downgrade() -> None:
    """Restore the original pending-keyed unique index."""
    op.drop_index(
        "uq_attestor_applications_user_submitted",
        table_name="attestor_applications",
    )
    op.create_index(
        "uq_attestor_applications_user_pending",
        "attestor_applications",
        ["user_id"],
        unique=True,
        postgresql_where=text("status = 'pending'"),
    )
