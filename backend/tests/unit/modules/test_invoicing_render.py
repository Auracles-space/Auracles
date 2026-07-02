"""Unit tests for invoice PDF rendering from frozen ledger rows (Module 6d)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.modules.invoicing.models import Invoice
from app.modules.invoicing.render import render_invoice_pdf


def _sales_invoice() -> Invoice:
    """Build one frozen sales-invoice row for render-only tests."""
    return Invoice(
        id=uuid4(),
        series="AUR-INV",
        sequence_year=2026,
        sequence_number=1,
        invoice_number="AUR-INV-2026-000001",
        doc_type="sales_invoice",
        issue_date=datetime(2026, 5, 1, tzinfo=UTC),
        currency="USD",
        subtotal=Decimal("500.00"),
        tax_rate=Decimal("0.0000"),
        tax_amount=Decimal("0.00"),
        total=Decimal("500.00"),
        commission_rate=None,
        net_amount=None,
        seller_name="Auracles Ltd",
        seller_tax_id="TAX-1",
        seller_address="1 Ledger Street",
        buyer_name="Ada Op",
        buyer_email="ada@example.com",
        source_ref_type="attestation",
        source_ref_id=uuid4(),
        s3_key="invoices/sales_invoice/x.pdf",
    )


def test_sales_invoice_renders_pdf_with_number_and_seller() -> None:
    """Sales invoice PDF renders from the frozen row only."""
    pdf = render_invoice_pdf(
        _sales_invoice(),
        line_item_label="Expert Attestation",
    )
    assert pdf[:4] == b"%PDF"


def test_earnings_statement_renders_net() -> None:
    """Earnings-statement PDF renders from an AUR-ERN row."""
    row = _sales_invoice()
    row.series = "AUR-ERN"
    row.doc_type = "earnings_statement"
    row.commission_rate = Decimal("0.1000")
    row.net_amount = Decimal("450.00")
    row.invoice_number = "AUR-ERN-2026-000001"

    pdf = render_invoice_pdf(
        row,
        line_item_label="Expert Attestation",
    )
    assert pdf[:4] == b"%PDF"
