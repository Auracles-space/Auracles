"""Add org attestor trial notification types.

Supports the org-as-attestor calibration flow: the nominee must receive a
durable notification both when nominated (``org_attestor_trial_nominated``)
and when a platform admin starts the trial (``org_attestor_trial_assigned``).
Both are stored in the ``type`` column typed by ``notification_type_enum``,
so the enum must include them or the worker insert fails silently and the
nominee is never told.

Revision ID: 2026_07_14_0083
Revises: 2026_07_14_0082
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_07_14_0083"
down_revision: str | Sequence[str] | None = "2026_07_14_0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the trial nomination and assignment notification labels."""
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
        "'org_attestor_trial_nominated'"
    )
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
        "'org_attestor_trial_assigned'"
    )


def downgrade() -> None:
    """Leave additive enum labels in place; purge rows that use them.

    Postgres cannot drop an enum value, so downgrade only removes notifications
    stored under the new labels to keep the column readable by the prior code.
    """
    op.execute(
        "DELETE FROM notifications WHERE type::text IN "
        "('org_attestor_trial_nominated', 'org_attestor_trial_assigned')"
    )
