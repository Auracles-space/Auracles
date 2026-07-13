"""Add milestone_plan_finalized notification and workspace event types.

Lets ``finalize_milestone_plan`` notify the Operator that the Contributor
finalized the Milestone plan (escrow funding is the next step) and record the
finalization in the workspace collaboration timeline, mirroring the existing
``milestone_plan_reopened`` event. Without these labels the Operator had no
signal that the plan was ready to fund.

Revision ID: 2026_07_13_0081
Revises: 2026_07_13_0080
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_07_13_0081"
down_revision: str | Sequence[str] | None = "2026_07_13_0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the milestone_plan_finalized notification and workspace event labels."""
    op.execute(
        "ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
        "'milestone_plan_finalized'"
    )
    op.execute(
        "ALTER TYPE workspace_system_event_enum ADD VALUE IF NOT EXISTS "
        "'milestone_plan_finalized'"
    )


def downgrade() -> None:
    """Leave the additive enum labels in place; drop any rows that used them."""
    op.execute(
        "DELETE FROM notifications WHERE type::text = 'milestone_plan_finalized'"
    )
    op.execute(
        "DELETE FROM workspace_messages "
        "WHERE system_event::text = 'milestone_plan_finalized'"
    )
