"""Store admin reasons for org and capability suspensions; owner notification labels.

Slice 2 of the organizations rework (docs/superpowers/specs/
2026-09-13-org-onboarding-journey-design.md). Admins used to suspend an
organization or suspend/revoke a capability with no reason and no notice, so
the owner saw a bare "actions are disabled" banner. The reason now lives on
the row it explains (cleared on reinstate) and the owner is notified under
the new labels. Member removal, role change, ownership transfer, and trial
decisions gain labels too.

Revision ID: 2026_09_13_0103
Revises: 2026_09_10_0102
Create Date: 2026-09-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_09_13_0103"
down_revision: str | Sequence[str] | None = "2026_09_10_0102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_LABELS: tuple[str, ...] = (
    "org_suspended",
    "org_reinstated",
    "org_capability_suspended",
    "org_capability_reinstated",
    "org_capability_revoked",
    "org_attestor_trial_decided",
    "org_member_removed",
    "org_member_role_changed",
    "org_ownership_transferred",
)


def upgrade() -> None:
    """Add reason columns and the owner-facing notification labels."""
    op.add_column(
        "organizations",
        sa.Column("suspension_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "org_capabilities",
        sa.Column("status_reason", sa.Text(), nullable=True),
    )
    for label in NEW_LABELS:
        op.execute(
            f"ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS '{label}'"
        )


def downgrade() -> None:
    """Drop the reason columns; purge rows under labels Postgres cannot drop."""
    labels = ", ".join(f"'{label}'" for label in NEW_LABELS)
    op.execute(f"DELETE FROM notifications WHERE type::text IN ({labels})")
    op.drop_column("org_capabilities", "status_reason")
    op.drop_column("organizations", "suspension_reason")
