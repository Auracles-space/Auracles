"""Invoicing ledger models — immutable issued-invoice register + gapless counter.

Maps to: FR-FIN-003.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models.base import CreatedAtMixin


class Invoice(CreatedAtMixin, Base):
    """Immutable issued-invoice snapshot row."""

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint(
            "series",
            "sequence_year",
            "sequence_number",
            name="uq_invoices_series_seq",
        ),
        UniqueConstraint("invoice_number", name="uq_invoices_number"),
        UniqueConstraint(
            "source_ref_type",
            "source_ref_id",
            "doc_type",
            name="uq_invoices_source_doc",
        ),
        CheckConstraint("subtotal >= 0", name="ck_invoices_subtotal_nonnegative"),
        CheckConstraint("total >= 0", name="ck_invoices_total_nonnegative"),
        CheckConstraint("tax_rate >= 0", name="ck_invoices_tax_rate_nonnegative"),
        Index("idx_invoices_source", "source_ref_type", "source_ref_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    series: Mapped[str] = mapped_column(String(20), nullable=False)
    sequence_year: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(32), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    issue_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    commission_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    seller_name: Mapped[str] = mapped_column(String(255), nullable=False)
    seller_tax_id: Mapped[str] = mapped_column(String(255), nullable=False)
    seller_address: Mapped[str] = mapped_column(String(500), nullable=False)
    buyer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    buyer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    source_ref_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_ref_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)


class InvoiceCounter(Base):
    """Gapless per-series per-year invoice counter."""

    __tablename__ = "invoice_counters"

    series: Mapped[str] = mapped_column(String(20), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
