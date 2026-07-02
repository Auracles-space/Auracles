"""Add shared invoicing ledger and gapless counters.

Creates the immutable issued-invoice register and the per-series/year counter
table used to allocate gapless invoice numbers for sales invoices and earnings
statements.

Maps to: FR-FIN-003.

Revision ID: 2026_07_02_0056
Revises: 2026_07_02_0055
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_02_0056"
down_revision: str | Sequence[str] | None = "2026_07_02_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create invoice counters and immutable invoice rows."""
    op.create_table(
        "invoice_counters",
        sa.Column("series", sa.String(length=20), primary_key=True),
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column(
            "last_number",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_table(
        "invoices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("series", sa.String(length=20), nullable=False),
        sa.Column("sequence_year", sa.Integer(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("invoice_number", sa.String(length=32), nullable=False),
        sa.Column("doc_type", sa.String(length=50), nullable=False),
        sa.Column(
            "issue_date",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("commission_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("net_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("seller_name", sa.String(length=255), nullable=False),
        sa.Column("seller_tax_id", sa.String(length=255), nullable=False),
        sa.Column("seller_address", sa.String(length=500), nullable=False),
        sa.Column("buyer_name", sa.String(length=255), nullable=False),
        sa.Column("buyer_email", sa.String(length=255), nullable=False),
        sa.Column("source_ref_type", sa.String(length=50), nullable=False),
        sa.Column("source_ref_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("s3_key", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "series",
            "sequence_year",
            "sequence_number",
            name="uq_invoices_series_seq",
        ),
        sa.UniqueConstraint("invoice_number", name="uq_invoices_number"),
        sa.UniqueConstraint(
            "source_ref_type",
            "source_ref_id",
            "doc_type",
            name="uq_invoices_source_doc",
        ),
        sa.CheckConstraint(
            "subtotal >= 0",
            name="ck_invoices_subtotal_nonnegative",
        ),
        sa.CheckConstraint("total >= 0", name="ck_invoices_total_nonnegative"),
        sa.CheckConstraint(
            "tax_rate >= 0",
            name="ck_invoices_tax_rate_nonnegative",
        ),
    )
    op.create_index(
        "idx_invoices_source",
        "invoices",
        ["source_ref_type", "source_ref_id"],
    )


def downgrade() -> None:
    """Drop invoice rows and counters."""
    op.drop_index("idx_invoices_source", table_name="invoices")
    op.drop_table("invoices")
    op.drop_table("invoice_counters")
