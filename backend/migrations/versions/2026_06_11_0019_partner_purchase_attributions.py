"""Add Partner API purchase attribution table.

Supports Phase 5a Slice 6 by linking a pending purchase transaction to the
Partner API key that initiated it while preserving the transaction's Framework
reference for the normal license webhook flow.

Revision ID: 2026_06_11_0019
Revises: 2026_06_11_0018
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_11_0019"
down_revision: str | Sequence[str] | None = "2026_06_11_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the Partner purchase attribution table."""
    op.create_table(
        "partner_purchase_attributions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "developer_account_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("framework_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("buyer_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("license_type", sa.String(length=50), nullable=False),
        sa.Column("tier_at_sale", sa.SmallInteger(), nullable=False),
        sa.Column("tier_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"]),
        sa.ForeignKeyConstraint(
            ["developer_account_id"],
            ["developer_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["framework_id"], ["frameworks.id"]),
        sa.ForeignKeyConstraint(["buyer_user_id"], ["users.id"]),
        sa.UniqueConstraint(
            "transaction_id",
            name="uq_partner_purchase_attr_transaction",
        ),
    )
    op.create_index(
        "idx_partner_purchase_attr_key_transaction",
        "partner_purchase_attributions",
        ["api_key_id", "transaction_id"],
    )
    op.create_index(
        "idx_partner_purchase_attr_developer",
        "partner_purchase_attributions",
        ["developer_account_id", "created_at"],
    )


def downgrade() -> None:
    """Remove the Partner purchase attribution table."""
    op.drop_index(
        "idx_partner_purchase_attr_developer",
        table_name="partner_purchase_attributions",
    )
    op.drop_index(
        "idx_partner_purchase_attr_key_transaction",
        table_name="partner_purchase_attributions",
    )
    op.drop_table("partner_purchase_attributions")
