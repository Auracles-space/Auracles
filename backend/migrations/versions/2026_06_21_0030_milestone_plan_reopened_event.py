"""Add milestone_plan_reopened workspace system event.

Supports the reopen-while-unfunded flow (Phase 4a milestone management): when a
Project member reopens a finalized Milestone plan back to draft, a workspace
system message records it in the collaboration timeline so both parties see the
renegotiation.

Revision ID: 2026_06_21_0030
Revises: 2026_06_17_0029
Create Date: 2026-06-21
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_06_21_0030"
down_revision: str | Sequence[str] | None = "2026_06_17_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the milestone_plan_reopened workspace system event label."""
    op.execute(
        "ALTER TYPE workspace_system_event_enum ADD VALUE IF NOT EXISTS "
        "'milestone_plan_reopened'"
    )


def downgrade() -> None:
    """Drop messages using the additive label; the enum value stays in place."""
    op.execute(
        "DELETE FROM workspace_messages "
        "WHERE system_event::text = 'milestone_plan_reopened'"
    )
