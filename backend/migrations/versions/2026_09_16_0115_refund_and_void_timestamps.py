"""Add escrows.refunded_at and partner_commissions.voided_at, backfilled.

The monthly Treasury statement rebuilds past months from timestamps. An
escrow refund and a partner commission void had none, so a refunded escrow
vanished from "held" in every month and a voided commission vanished from
every month. Existing rows take their real time from the ledger
(``escrow_refunded`` events) and the audit log
(``partner_commission_voided``); a row with neither falls back to its
creation time, which matches how it was counted before.

Revision ID: 2026_09_16_0115
Revises: 2026_09_16_0114
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_09_16_0115"
down_revision: str | Sequence[str] | None = "2026_09_16_0114"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add both columns and backfill them for existing refunded/voided rows."""
    op.add_column(
        "escrows",
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "partner_commissions",
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE escrows AS e
        SET refunded_at = COALESCE(
            (
                SELECT max(fe.occurred_at) FROM financial_events AS fe
                WHERE fe.entity_type = 'escrow'
                  AND fe.entity_id = e.id
                  AND fe.event_type = 'escrow_refunded'
            ),
            e.held_at
        )
        WHERE e.status = 'refunded'
        """
    )
    op.execute(
        """
        UPDATE partner_commissions AS pc
        SET voided_at = COALESCE(
            (
                SELECT max(al.created_at) FROM audit_logs AS al
                WHERE al.action = 'partner_commission_voided'
                  AND al.target_type = 'partner_commission'
                  AND al.target_id = pc.id
            ),
            pc.created_at
        )
        WHERE pc.status = 'voided'
        """
    )


def downgrade() -> None:
    """Drop both timestamp columns."""
    op.drop_column("partner_commissions", "voided_at")
    op.drop_column("escrows", "refunded_at")
