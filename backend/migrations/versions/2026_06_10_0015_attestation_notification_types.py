"""Add attestation lifecycle notification types.

Revision ID: 2026_06_10_0015
Revises: 2026_06_10_0014
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_06_10_0015"
down_revision: str | Sequence[str] | None = "2026_06_10_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADDED_NOTIFICATION_TYPES = (
    "attestation_fee_funded",
    "attestation_offer_received",
    "attestation_accepted",
    "attestation_declined",
    "attestation_offer_expired",
    "attestation_reassigned",
    "attestation_needs_admin",
    "attestation_released",
    "attestation_disputed",
    "attestation_dispute_resolved",
    "attestation_refunded",
)

BASE_NOTIFICATION_TYPES = (
    "project_created",
    "project_extended",
    "project_closed",
    "proposal_submitted",
    "proposal_accepted",
    "proposal_rejected",
    "proposal_withdrawn",
    "proposal_expired",
    "amendment_proposed",
    "amendment_accepted",
    "amendment_rejected",
    "amendment_withdrawn",
    "amendment_expired",
    "milestone_created",
    "milestone_updated",
    "milestone_funded",
    "deliverable_submitted",
    "deliverable_approved",
    "deliverable_auto_approved",
    "deliverable_revision_requested",
    "dispute_raised",
    "dispute_escalated",
    "dispute_resolved_release",
    "dispute_resolved_refund",
    "dispute_resolved_split",
    "workspace_file_quarantined",
    "attestation_requested",
    "attestation_assigned",
    "attestation_report_submitted",
    "attestation_published",
    "attestation_rejected",
)


def _quoted_values(values: tuple[str, ...]) -> str:
    """Return SQL enum values quoted for a CREATE TYPE statement."""
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    """Add attestation notification labels to the existing enum."""
    for notification_type in ADDED_NOTIFICATION_TYPES:
        op.execute(
            f"ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS "
            f"'{notification_type}'"
        )


def downgrade() -> None:
    """Remove attestation notification labels by recreating the enum."""
    added_values = _quoted_values(ADDED_NOTIFICATION_TYPES)
    base_values = _quoted_values(BASE_NOTIFICATION_TYPES)
    op.execute(f"DELETE FROM notifications WHERE type::text IN ({added_values})")
    op.execute("ALTER TYPE notification_type_enum RENAME TO notification_type_enum_old")
    op.execute(f"CREATE TYPE notification_type_enum AS ENUM ({base_values})")
    op.execute(
        """
        ALTER TABLE notifications
        ALTER COLUMN type TYPE notification_type_enum
        USING type::text::notification_type_enum
        """
    )
    op.execute("DROP TYPE notification_type_enum_old")
