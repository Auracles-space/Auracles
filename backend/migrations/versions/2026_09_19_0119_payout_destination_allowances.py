"""Add payout_destination_allowances for admin-approved account sharing.

One bank account may back several owners, which is the ordinary sole trader
case, but past a small ceiling it stops looking like a sole trader and starts
looking like a payout funnel, so registration is refused and an admin is asked
to look. That ceiling is a prompt rather than a verdict: a group of related
trading entities paying into one treasury account is legitimate and would
otherwise be permanently stuck. This table records that a human looked, said
yes, and how far.

Keyed by the provider and lookup hash that identify a destination everywhere
else, so an allowance outlives the individual payout accounts referencing it.

Revision ID: 2026_09_19_0119
Revises: 2026_09_19_0118
Create Date: 2026-09-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_09_19_0119"
down_revision: str | Sequence[str] | None = "2026_09_19_0118"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the admin allowance table for shared payout destinations."""
    op.create_table(
        "payout_destination_allowances",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "provider",
            sa.dialects.postgresql.ENUM(
                "stripe",
                "paystack",
                name="payment_provider_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "provider_account_lookup_hash",
            sa.String(64),
            nullable=False,
        ),
        sa.Column("max_owners", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "approved_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_account_lookup_hash",
            name="uq_payout_destination_allowances_destination",
        ),
        sa.CheckConstraint(
            "max_owners > 0",
            name="ck_payout_destination_allowances_max_owners_positive",
        ),
    )


def downgrade() -> None:
    """Drop the allowance table.

    Destinations allowed past the ceiling revert to it. Nothing already
    registered is disturbed; only further owners are refused.
    """
    op.drop_table("payout_destination_allowances")
