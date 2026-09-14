"""Org lifecycle audit columns and the Slice B/C notification labels.

Slice B of the organizations end-to-end design (docs/superpowers/specs/
2026-09-14-organizations-end-to-end-design.md). Deactivation kept no record
of who closed the organization or why, and suspension stored the reason but
not the admin; both now sit on the row so the admin console can show them
and reactivation can clear them. The notification labels cover every org
event the owner journey and the money surfaces were silent about: creation,
profile edits, wind-down and reopen, KYB submission, invitation lifecycle,
license and framework changes, purchases, payouts, and invoices.

Revision ID: 2026_09_14_0105
Revises: 2026_09_14_0104
Create Date: 2026-09-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "2026_09_14_0105"
down_revision: str | Sequence[str] | None = "2026_09_14_0104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_LABELS: tuple[str, ...] = (
    "org_created",
    "org_profile_updated",
    "org_deactivated",
    "org_reactivated",
    "org_kyb_submitted",
    "org_invitation_revoked",
    "org_invitation_expired",
    "org_invitation_accepted",
    "org_invitation_declined",
    "org_license_granted",
    "org_license_revoked",
    "org_framework_suspended",
    "org_framework_published",
    "org_purchase_completed",
    "org_purchase_failed",
    "org_payout_requested",
    "org_payout_completed",
    "org_payout_failed",
    "org_invoice_ready",
)
# Labels this migration introduces; the accept/decline pair predates it and
# must survive a downgrade, so only these are purged.
_INTRODUCED_LABELS: tuple[str, ...] = tuple(
    label
    for label in NEW_LABELS
    if label not in {"org_invitation_accepted", "org_invitation_declined"}
)


def upgrade() -> None:
    """Add the lifecycle actor/reason columns and the notification labels."""
    op.add_column(
        "organizations",
        sa.Column(
            "deactivated_by",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("deactivation_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "suspended_by",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    for label in NEW_LABELS:
        op.execute(
            f"ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS '{label}'"
        )


def downgrade() -> None:
    """Drop the columns; purge rows under labels Postgres cannot drop."""
    labels = ", ".join(f"'{label}'" for label in _INTRODUCED_LABELS)
    op.execute(f"DELETE FROM notifications WHERE type::text IN ({labels})")
    op.drop_column("organizations", "suspended_by")
    op.drop_column("organizations", "deactivation_reason")
    op.drop_column("organizations", "deactivated_by")
