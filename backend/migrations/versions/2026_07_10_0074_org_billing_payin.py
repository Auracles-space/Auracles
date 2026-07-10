"""Add org billing customer and transaction payer org XOR.

Supports Task 4 in docs/superpowers/plans/2026-07-10-org-operator.md by
adding the additive org pay-in surfaces: an organization Stripe customer and
transaction payer ownership that resolves to either a user or an organization.

Revision ID: 2026_07_10_0074
Revises: 2026_07_10_0073
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_10_0074"
down_revision: str | Sequence[str] | None = "2026_07_10_0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add org Stripe customer storage and payer XOR on transactions."""
    op.add_column(
        "organizations",
        sa.Column("stripe_customer_id", sa.Text(), nullable=True),
    )

    op.add_column(
        "transactions",
        sa.Column("payer_org_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("transactions", "payer_id", nullable=True)
    op.create_foreign_key(
        "fk_transactions_payer_org_id",
        "transactions",
        "organizations",
        ["payer_org_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_transactions_payer_xor",
        "transactions",
        "(payer_id IS NULL) != (payer_org_id IS NULL)",
    )
    op.create_index("idx_transactions_payer_org", "transactions", ["payer_org_id"])


def downgrade() -> None:
    """Remove org billing pay-in columns and restore the user-only payer schema.

    This downgrade restores the pre-org dev schema and assumes no org-payer
    rows remain before `transactions.payer_id` is tightened back to NOT NULL.
    """

    op.execute("DROP INDEX IF EXISTS idx_transactions_payer_org")
    op.execute(
        "ALTER TABLE transactions DROP CONSTRAINT IF EXISTS ck_transactions_payer_xor"
    )
    op.execute(
        "ALTER TABLE transactions DROP CONSTRAINT IF EXISTS "
        "fk_transactions_payer_org_id"
    )
    op.alter_column("transactions", "payer_id", nullable=False)
    op.drop_column("transactions", "payer_org_id")

    op.drop_column("organizations", "stripe_customer_id")
