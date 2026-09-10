"""Invoice PDF rendering from frozen ledger rows.

Renders sales invoices and earnings statements using only the immutable
``Invoice`` snapshot row plus a human line-item label supplied by the caller.
Maps to: FR-FIN-003 and FR-FIN-004.

The two documents share one stylesheet and one page frame, differing only in
their body. They are the most formal artefacts Auracles produces — a buyer
files the sales invoice with their accounts, and an Attestor's earnings
statement is a record of income — so they carry the brand deliberately rather
than defaulting to whatever the renderer picks.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Final

from jinja2 import Environment, Template

from app.modules.invoicing.models import Invoice
from app.modules.invoicing.service import DOC_EARNINGS_STATEMENT, DOC_SALES_INVOICE

_CENTS: Final[Decimal] = Decimal("0.01")
_PERCENT: Final[Decimal] = Decimal("100")

# Resolved relative to this module so WeasyPrint finds the wordmark wherever
# the worker image places the package.
_ASSET_DIR: Final[Path] = Path(__file__).parent / "assets"

_TEMPLATE_ENV = Environment(autoescape=True)

# Brand Book v1.0, light mode. The invoice is a printed document, so it commits
# to the light palette rather than adapting: Background #FFFFFB, Surface 1
# #F8F6F2, Accent #C74634.
#
# WeasyPrint renders through Pango, not a browser engine: no flexbox, no grid.
# Every multi-column arrangement below is `display: table`, which is why this
# stylesheet looks older than the rest of the codebase. It is not a stale file.
_BASE_STYLES: Final[str] = """
  @page {
    size: A4;
    margin: 18mm 16mm 22mm 16mm;
    @bottom-left {
      content: "Auracles \\2014 knowledge marketplace";
      font-family: 'Inter', 'DejaVu Sans', sans-serif;
      font-size: 7.5pt;
      color: #8a8378;
    }
    @bottom-right {
      content: "Page " counter(page) " of " counter(pages);
      font-family: 'Inter', 'DejaVu Sans', sans-serif;
      font-size: 7.5pt;
      color: #8a8378;
    }
  }
  body {
    font-family: 'Inter', 'DejaVu Sans', sans-serif;
    font-size: 9.5pt;
    line-height: 1.6;
    color: #171717;
    background: #FFFFFB;
    margin: 0;
  }
  .masthead { display: table; width: 100%; }
  .masthead .mark { display: table-cell; vertical-align: top; width: 46%; }
  .masthead .meta {
    display: table-cell;
    vertical-align: top;
    text-align: right;
  }
  .mark img { width: 118px; }
  .doc-type {
    font-size: 15pt;
    font-weight: 700;
    letter-spacing: -0.02em;
    margin: 0;
  }
  .doc-number {
    font-family: 'DejaVu Sans Mono', monospace;
    font-size: 10pt;
    color: #C74634;
    margin: 2px 0 0 0;
  }
  .rule {
    height: 2px;
    background: #171717;
    margin: 14px 0 0 0;
  }
  .label {
    font-size: 7pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    color: #8a8378;
    margin: 0 0 6px 0;
  }
  /* The cards are the table cells themselves, not boxes nested inside them.
     Nested boxes size to their own content, so a three-line seller address
     next to a two-line buyer leaves one card visibly short. As cells they
     share the row's height, and border-spacing supplies the gutter that the
     padding on a wrapper would otherwise have provided. */
  .parties {
    display: table;
    width: 100%;
    margin-top: 20px;
    border-collapse: separate;
    border-spacing: 14px 0;
  }
  .parties .card { display: table-cell; vertical-align: top; width: 50%; }
  .parties { margin-left: -14px; margin-right: -14px; }
  .card {
    background: #F8F6F2;
    border: 1px solid #E6E1D8;
    border-radius: 12px;
    padding: 12px 14px;
  }
  .card .name { font-weight: 700; margin: 0; }
  .card p { margin: 0; }
  .card .detail { color: #5f6368; }
  .facts { display: table; width: 100%; margin-top: 14px; }
  .facts .fact { display: table-cell; vertical-align: top; }
  .facts .fact p { margin: 0; }
  .facts .value { font-weight: 600; }
  .items { width: 100%; border-collapse: collapse; margin-top: 26px; }
  .items thead th {
    font-size: 7pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    color: #8a8378;
    text-align: left;
    padding: 0 0 8px 0;
    border-bottom: 1.5px solid #171717;
  }
  .items tbody td {
    padding: 13px 0;
    border-bottom: 1px solid #E6E1D8;
    vertical-align: top;
  }
  .items .amount { text-align: right; white-space: nowrap; }
  .items .item-name { font-weight: 600; }
  .summary { width: 260px; margin-left: auto; margin-top: 18px; }
  .summary table { width: 100%; border-collapse: collapse; }
  .summary td { padding: 5px 0; }
  .summary .amount { text-align: right; white-space: nowrap; }
  .summary .muted td { color: #5f6368; }
  .summary .total td {
    border-top: 2px solid #171717;
    padding-top: 10px;
    font-size: 12pt;
    font-weight: 700;
  }
  .summary .total .amount { color: #C74634; }
  .note {
    margin-top: 34px;
    padding-top: 12px;
    border-top: 1px solid #E6E1D8;
    font-size: 8pt;
    line-height: 1.6;
    color: #8a8378;
  }
"""


def _template(body: str) -> Template:
    """Compile one page template with the shared stylesheet already inlined.

    The stylesheet is substituted before compilation rather than passed as a
    render variable. This environment autoescapes — correctly, since invoice
    rows carry user-supplied names — and escaping applies to every variable
    equally, so a CSS payload would come through with its quotes turned into
    entities. That breaks each `font-family` declaration silently: the document
    still renders, just in the renderer's default serif with none of the brand
    typography, and nothing in the output says why.
    """
    return _TEMPLATE_ENV.from_string(body.replace("/* STYLES */", _BASE_STYLES))


_SALES_TEMPLATE = _template(
    """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <style>/* STYLES */</style>
      </head>
      <body>
        <div class="masthead">
          <div class="mark">
            <img src="auracles-wordmark.png" alt="Auracles">
          </div>
          <div class="meta">
            <p class="doc-type">Sales Invoice</p>
            <p class="doc-number">{{ invoice_number }}</p>
          </div>
        </div>
        <div class="rule"></div>

        <div class="parties">
          <div class="card">
            <p class="label">Seller</p>
            <p class="name">{{ seller_name }}</p>
            {% if seller_tax_id %}
              <p class="detail">Tax ID {{ seller_tax_id }}</p>
            {% endif %}
            {% if seller_address %}
              <p class="detail">{{ seller_address }}</p>
            {% endif %}
          </div>
          <div class="card">
            <p class="label">Billed to</p>
            <p class="name">{{ buyer_name }}</p>
            <p class="detail">{{ buyer_email }}</p>
          </div>
        </div>

        <div class="facts">
          <div class="fact">
            <p class="label">Issued</p>
            <p class="value">{{ issue_date }}</p>
          </div>
          <div class="fact">
            <p class="label">Currency</p>
            <p class="value">{{ currency }}</p>
          </div>
          <div class="fact">
            <p class="label">Amount due</p>
            <p class="value">{{ total }}</p>
          </div>
        </div>

        <table class="items">
          <thead>
            <tr>
              <th>Description</th>
              <th class="amount">Amount</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="item-name">{{ line_item_label }}</td>
              <td class="amount">{{ subtotal }}</td>
            </tr>
          </tbody>
        </table>

        <div class="summary">
          <table>
            <tbody>
              <tr class="muted">
                <td>Subtotal</td>
                <td class="amount">{{ subtotal }}</td>
              </tr>
              <tr class="muted">
                <td>Tax ({{ tax_percent }})</td>
                <td class="amount">{{ tax_amount }}</td>
              </tr>
              <tr class="total">
                <td>Total</td>
                <td class="amount">{{ total }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <p class="note">
          This invoice is issued for a completed purchase on the Auracles
          marketplace and is payable in {{ currency }}. Amounts are final as
          recorded at the time of sale. Retain this document for your records.
        </p>
      </body>
    </html>
    """
)

_EARNINGS_TEMPLATE = _template(
    """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <style>/* STYLES */</style>
      </head>
      <body>
        <div class="masthead">
          <div class="mark">
            <img src="auracles-wordmark.png" alt="Auracles">
          </div>
          <div class="meta">
            <p class="doc-type">Earnings Statement</p>
            <p class="doc-number">{{ invoice_number }}</p>
          </div>
        </div>
        <div class="rule"></div>

        <div class="parties">
          <div class="card">
            <p class="label">Attestor</p>
            <p class="name">{{ buyer_name }}</p>
            <p class="detail">{{ buyer_email }}</p>
          </div>
          <div class="card">
            <p class="label">Issued by</p>
            <p class="name">{{ seller_name }}</p>
            {% if seller_tax_id %}
              <p class="detail">Tax ID {{ seller_tax_id }}</p>
            {% endif %}
            {% if seller_address %}
              <p class="detail">{{ seller_address }}</p>
            {% endif %}
          </div>
        </div>

        <div class="facts">
          <div class="fact">
            <p class="label">Issued</p>
            <p class="value">{{ issue_date }}</p>
          </div>
          <div class="fact">
            <p class="label">Currency</p>
            <p class="value">{{ currency }}</p>
          </div>
          <div class="fact">
            <p class="label">Net earnings</p>
            <p class="value">{{ net_amount }}</p>
          </div>
        </div>

        <table class="items">
          <thead>
            <tr>
              <th>Engagement</th>
              <th class="amount">Gross fee</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="item-name">{{ line_item_label }}</td>
              <td class="amount">{{ subtotal }}</td>
            </tr>
          </tbody>
        </table>

        <div class="summary">
          <table>
            <tbody>
              <tr class="muted">
                <td>Gross fee</td>
                <td class="amount">{{ subtotal }}</td>
              </tr>
              <tr class="muted">
                <td>Commission ({{ commission_percent }})</td>
                <td class="amount">&minus;{{ commission_amount }}</td>
              </tr>
              <tr class="total">
                <td>Net earnings</td>
                <td class="amount">{{ net_amount }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <p class="note">
          This statement records earnings from a completed Attestation
          engagement, net of the platform commission in force at the time the
          fee settled. It is a record of income, not a request for payment.
        </p>
      </body>
    </html>
    """
)


def _money(value: Decimal, currency: str) -> str:
    """Format one money value from the frozen ledger row.

    The ISO code leads rather than a currency symbol. Symbols are ambiguous
    across the rails Auracles settles on — a bare ``$`` says nothing about
    which dollar — and the naira sign risks a missing glyph in whatever font
    the renderer resolves. ``NGN 149,000.00`` survives both problems and is
    what cross-border invoices conventionally carry.
    """
    return f"{currency} {value.quantize(_CENTS):,}"


def _percent(value: Decimal | None) -> str:
    """Format a decimal rate as a display percentage."""
    if value is None:
        return "0%"
    return f"{(value * _PERCENT).normalize()}%"


def render_invoice_pdf(invoice: Invoice, *, line_item_label: str) -> bytes:
    """Render one invoice or earnings statement PDF from a frozen row.

    Args:
        invoice: The immutable ledger snapshot to render. Nothing outside this
            row and ``line_item_label`` reaches the page, so a reissued PDF is
            byte-comparable to the original.
        line_item_label: Human description of what was sold or performed.

    Returns:
        The rendered PDF bytes.

    Raises:
        ValueError: If the row carries an unsupported ``doc_type``.
    """
    # Imported at call time, not module scope: WeasyPrint dlopens pango/glib on
    # import, and this module is reachable from the API's import graph even
    # though only the Celery worker ever renders a PDF. A module-scope import
    # would make the API refuse to boot wherever those native libraries are
    # absent (any machine that is not the worker image).
    from weasyprint import HTML  # type: ignore[import-untyped]

    base_context = {
        "invoice_number": invoice.invoice_number,
        "issue_date": invoice.issue_date.date().isoformat(),
        "currency": invoice.currency,
        "line_item_label": line_item_label,
        "seller_name": invoice.seller_name,
        "seller_tax_id": invoice.seller_tax_id,
        "seller_address": invoice.seller_address,
        "buyer_name": invoice.buyer_name,
        "buyer_email": invoice.buyer_email,
        "subtotal": _money(invoice.subtotal, invoice.currency),
        "tax_amount": _money(invoice.tax_amount, invoice.currency),
        "tax_percent": _percent(invoice.tax_rate),
        "total": _money(invoice.total, invoice.currency),
        "commission_percent": _percent(invoice.commission_rate),
        "commission_amount": _money(
            (invoice.subtotal - (invoice.net_amount or invoice.subtotal)).quantize(
                _CENTS
            ),
            invoice.currency,
        ),
        "net_amount": _money(invoice.net_amount or Decimal("0.00"), invoice.currency),
    }
    if invoice.doc_type == DOC_SALES_INVOICE:
        html = _SALES_TEMPLATE.render(**base_context)
    elif invoice.doc_type == DOC_EARNINGS_STATEMENT:
        html = _EARNINGS_TEMPLATE.render(**base_context)
    else:
        raise ValueError(f"Unsupported invoice doc_type: {invoice.doc_type}")
    # base_url resolves the wordmark; without it the relative src is dropped
    # and the document renders unbranded rather than failing loudly.
    return bytes(HTML(string=html, base_url=str(_ASSET_DIR / "x")).write_pdf())
