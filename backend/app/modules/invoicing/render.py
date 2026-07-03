"""Invoice PDF rendering from frozen ledger rows.

Renders sales invoices and earnings statements using only the immutable
``Invoice`` snapshot row plus a human line-item label supplied by the caller.
Maps to: FR-FIN-003 and FR-FIN-004.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from jinja2 import Environment
from weasyprint import HTML  # type: ignore[import-untyped]

from app.modules.invoicing.models import Invoice
from app.modules.invoicing.service import DOC_EARNINGS_STATEMENT, DOC_SALES_INVOICE

_CENTS: Final[Decimal] = Decimal("0.01")
_PERCENT: Final[Decimal] = Decimal("100")

_TEMPLATE_ENV = Environment(autoescape=True)

_SALES_TEMPLATE = _TEMPLATE_ENV.from_string(
    """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <style>
          @page { size: A4; margin: 24px; }
          body { font-family: sans-serif; color: #171717; }
          h1 { margin-bottom: 4px; }
          .muted { color: #5f6368; }
          .grid { display: table; width: 100%; margin-top: 18px; }
          .col { display: table-cell; vertical-align: top; width: 50%; }
          .card {
            border: 1px solid #d7d3cc;
            padding: 12px;
            border-radius: 6px;
          }
          table { width: 100%; border-collapse: collapse; margin-top: 24px; }
          th, td {
            text-align: left;
            padding: 10px 0;
            border-bottom: 1px solid #ece7df;
          }
          .amount { text-align: right; }
          .summary { width: 320px; margin-left: auto; margin-top: 24px; }
          .summary td { border-bottom: none; }
          .summary .total td { border-top: 2px solid #171717; font-weight: 700; }
        </style>
      </head>
      <body>
        <h1>Auracles Sales Invoice</h1>
        <p class="muted">{{ invoice_number }} · Issued {{ issue_date }}</p>
        <div class="grid">
          <div class="col">
            <div class="card">
              <strong>Seller</strong>
              <p>{{ seller_name }}</p>
              <p>{{ seller_tax_id }}</p>
              <p>{{ seller_address }}</p>
            </div>
          </div>
          <div class="col">
            <div class="card">
              <strong>Buyer</strong>
              <p>{{ buyer_name }}</p>
              <p>{{ buyer_email }}</p>
            </div>
          </div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Item</th>
              <th class="amount">Amount</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{{ line_item_label }}</td>
              <td class="amount">{{ subtotal }}</td>
            </tr>
          </tbody>
        </table>
        <table class="summary">
          <tbody>
            <tr>
              <td>Subtotal</td>
              <td class="amount">{{ subtotal }}</td>
            </tr>
            <tr>
              <td>Tax ({{ tax_percent }})</td>
              <td class="amount">{{ tax_amount }}</td>
            </tr>
            <tr class="total">
              <td>Total</td>
              <td class="amount">{{ total }}</td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    """
)

_EARNINGS_TEMPLATE = _TEMPLATE_ENV.from_string(
    """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <style>
          @page { size: A4; margin: 24px; }
          body { font-family: sans-serif; color: #171717; }
          h1 { margin-bottom: 4px; }
          .muted { color: #5f6368; }
          .card {
            border: 1px solid #d7d3cc;
            padding: 12px;
            border-radius: 6px;
            margin-top: 18px;
          }
          table { width: 100%; border-collapse: collapse; margin-top: 24px; }
          th, td {
            text-align: left;
            padding: 10px 0;
            border-bottom: 1px solid #ece7df;
          }
          .amount { text-align: right; }
          .summary { width: 360px; margin-left: auto; margin-top: 24px; }
          .summary td { border-bottom: none; }
          .summary .total td { border-top: 2px solid #171717; font-weight: 700; }
        </style>
      </head>
      <body>
        <h1>Auracles Earnings Statement</h1>
        <p class="muted">{{ invoice_number }} · Issued {{ issue_date }}</p>
        <div class="card">
          <strong>Attestor</strong>
          <p>{{ buyer_name }}</p>
          <p>{{ buyer_email }}</p>
        </div>
        <table>
          <thead>
            <tr>
              <th>Engagement</th>
              <th class="amount">Gross fee</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{{ line_item_label }}</td>
              <td class="amount">{{ subtotal }}</td>
            </tr>
          </tbody>
        </table>
        <table class="summary">
          <tbody>
            <tr>
              <td>Gross fee</td>
              <td class="amount">{{ subtotal }}</td>
            </tr>
            <tr>
              <td>Platform commission ({{ commission_percent }})</td>
              <td class="amount">{{ commission_amount }}</td>
            </tr>
            <tr class="total">
              <td>Net earnings</td>
              <td class="amount">{{ net_amount }}</td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    """
)


def _money(value: Decimal, currency: str) -> str:
    """Format one money value from the frozen ledger row."""
    return f"{value.quantize(_CENTS)} {currency}"


def _percent(value: Decimal | None) -> str:
    """Format a decimal rate as a display percentage."""
    if value is None:
        return "0%"
    return f"{(value * _PERCENT).normalize()}%"


def render_invoice_pdf(invoice: Invoice, *, line_item_label: str) -> bytes:
    """Render one invoice or earnings statement PDF from a frozen row."""
    base_context = {
        "invoice_number": invoice.invoice_number,
        "issue_date": invoice.issue_date.date().isoformat(),
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
    return bytes(HTML(string=html).write_pdf())
