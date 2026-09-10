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


def test_invoice_stylesheet_survives_template_escaping() -> None:
    """The rendered page must carry the brand font stack unescaped.

    The template environment autoescapes, correctly — invoice rows carry
    user-supplied buyer and seller names. But escaping applies to every
    variable equally, so passing the stylesheet in as one turned each quote
    into an entity and broke every `font-family` declaration. Nothing failed:
    the PDF still rendered, just in the renderer's default serif with none of
    the brand typography. Only looking at the document revealed it, so the
    stack is asserted on the markup instead.
    """
    from app.modules.invoicing.render import _SALES_TEMPLATE

    html = _SALES_TEMPLATE.render(
        invoice_number="AUR-INV-2026-000001",
        issue_date="2026-05-01",
        currency="NGN",
        line_item_label="Clinical Governance Framework",
        seller_name="Meridian Advisory Partners Ltd",
        seller_tax_id="NG-TIN-20481553",
        seller_address="14 Kofo Abayomi Street, Lagos",
        buyer_name="Adaeze Okonkwo",
        buyer_email="adaeze@example.com",
        subtotal="NGN 485,000.00",
        tax_amount="NGN 36,375.00",
        tax_percent="7.5%",
        total="NGN 521,375.00",
    )

    assert "font-family: 'Inter', 'DejaVu Sans', sans-serif" in html
    assert "&#39;" not in html


def test_invoice_escapes_names_from_the_ledger_row() -> None:
    """Buyer and seller names are still escaped after the stylesheet change.

    Inlining the stylesheet before compilation must not have been done by
    turning autoescaping off: these names originate from user input.
    """
    from app.modules.invoicing.render import _SALES_TEMPLATE

    html = _SALES_TEMPLATE.render(
        invoice_number="AUR-INV-2026-000001",
        issue_date="2026-05-01",
        currency="NGN",
        line_item_label="Framework",
        seller_name="<script>alert(1)</script>",
        seller_tax_id="",
        seller_address="",
        buyer_name="Ada Op",
        buyer_email="ada@example.com",
        subtotal="NGN 1.00",
        tax_amount="NGN 0.00",
        tax_percent="0%",
        total="NGN 1.00",
    )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
