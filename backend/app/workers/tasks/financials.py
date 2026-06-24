"""Financial Celery tasks for invoices and future payout processing."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from jinja2 import Template
from loguru import logger
from sqlalchemy import select
from weasyprint import HTML  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.auth.models import User
from app.modules.financials.invoices import purchase_invoice_key
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework, License
from app.workers.async_runner import run_async
from app.workers.celery_app import app

INVOICE_TEMPLATE = Template(
    """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=Poppins:wght@400;500;600&display=swap');
      
      @page {
        size: A4;
        margin: 2cm 1.5cm;
      }
      
      body {
        font-family: 'Poppins', 'Helvetica Neue', Arial, sans-serif;
        color: #111827;
        margin: 0;
        padding: 0;
        line-height: 1.5;
        background-color: #ffffff;
      }
      
      .invoice-container {
        position: relative;
        width: 100%;
      }
      
      header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 3px solid #C74634;
        padding-bottom: 24px;
        margin-bottom: 40px;
      }
      
      .logo-container {
        display: flex;
        align-items: center;
      }
      
      .logo-img {
        height: 28px;
        width: auto;
        display: block;
      }
      
      .invoice-title-wrapper h1 {
        font-family: 'Inter', sans-serif;
        font-size: 32px;
        font-weight: 800;
        color: #C74634;
        margin: 0;
        letter-spacing: -0.02em;
      }
      
      .meta-grid {
        display: flex;
        justify-content: space-between;
        margin-bottom: 48px;
      }
      
      .meta-column {
        flex: 1;
        margin-right: 20px;
      }
      
      .meta-column:last-child {
        margin-right: 0;
        max-width: 300px;
      }
      
      .meta-column h3 {
        font-family: 'Inter', sans-serif;
        font-size: 11px;
        font-weight: 700;
        color: #C74634;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        margin-top: 0;
        margin-bottom: 12px;
        border-bottom: 1px solid #E5E7EB;
        padding-bottom: 6px;
      }
      
      .meta-column p {
        font-size: 13px;
        color: #374151;
        margin: 4px 0;
      }
      
      .meta-column p.highlight {
        font-weight: 600;
        color: #111827;
      }
      
      .mono-id {
        font-family: monospace;
        font-size: 11px;
        background: #F3F4F6;
        padding: 2px 6px;
        border-radius: 4px;
        color: #374151;
      }
      
      .stamp {
        position: absolute;
        top: 90px;
        right: 0;
        border: 4px double;
        padding: 8px 18px;
        font-size: 20px;
        font-weight: 800;
        font-family: 'Inter', sans-serif;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        transform: rotate(-10deg);
        border-radius: 6px;
        opacity: 0.85;
      }
      
      .stamp-completed {
        color: #16A34A;
        border-color: #16A34A;
      }
      
      .stamp-refunded {
        color: #DC2626;
        border-color: #DC2626;
      }
      
      .stamp-pending {
        color: #F59E0B;
        border-color: #F59E0B;
      }
      
      table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 30px;
        margin-bottom: 30px;
      }
      
      th {
        font-family: 'Inter', sans-serif;
        font-size: 12px;
        font-weight: 700;
        color: #4B5563;
        background-color: #F9FAFB;
        border-bottom: 2px solid #E5E7EB;
        padding: 12px 16px;
        text-align: left;
        text-transform: uppercase;
        letter-spacing: 0.05em;
      }
      
      td {
        font-size: 14px;
        color: #111827;
        border-bottom: 1px solid #E5E7EB;
        padding: 16px;
      }
      
      .td-product {
        font-weight: 600;
      }
      
      .td-license {
        font-size: 14px;
        color: #4B5563;
        font-weight: 500;
      }
      
      .text-right {
        text-align: right;
      }
      
      .summary-table {
        float: right;
        width: 280px;
        margin-top: 20px;
        margin-bottom: 30px;
        border-collapse: collapse;
      }
      
      .summary-table td {
        border: none;
        padding: 8px 16px;
        font-size: 14px;
        color: #4B5563;
      }
      
      .summary-table tr td:last-child {
        text-align: right;
      }
      
      .summary-table .total-row td {
        border-top: 2px solid #111827;
        font-family: 'Inter', sans-serif;
        font-size: 18px;
        font-weight: 800;
        color: #111827;
        padding-top: 12px;
      }
      
      footer {
        clear: both;
        margin-top: 80px;
        text-align: center;
        border-top: 1px solid #E5E7EB;
        padding-top: 24px;
        font-size: 11px;
        color: #9CA3AF;
      }
      
      .footer-slug {
        font-family: 'Inter', sans-serif;
        font-weight: 700;
        font-size: 10px;
        letter-spacing: 0.1em;
        color: #C74634;
        margin-top: 6px;
        text-transform: uppercase;
      }
    </style>
  </head>
  <body>
    <div class="invoice-container">
      {% if status == 'completed' %}
      <div class="stamp stamp-completed">PAID</div>
      {% elif status == 'refunded' %}
      <div class="stamp stamp-refunded">REFUNDED</div>
      {% else %}
      <div class="stamp stamp-pending">{{ status | upper }}</div>
      {% endif %}
      
      <header>
        <div class="logo-container">
          <img class="logo-img" src="{{ logo_url }}" alt="Auracles Logo">
        </div>
        <div class="invoice-title-wrapper">
          <h1>INVOICE</h1>
        </div>
      </header>
      
      <div class="meta-grid">
        <div class="meta-column">
          <h3>BILL TO</h3>
          <p class="highlight">{{ operator_name }}</p>
          <p>{{ operator_email }}</p>
        </div>
        <div class="meta-column">
          <h3>ISSUED BY</h3>
          <p class="highlight">Auracles Space</p>
          <p>no-reply@auracles.space</p>
        </div>
        <div class="meta-column">
          <h3>DETAILS</h3>
          <p><strong>Transaction:</strong>
            <span class="mono-id">{{ transaction_id }}</span></p>
          <p><strong>Status:</strong> {{ status | upper }}</p>
        </div>
      </div>
      
      <table>
        <thead>
          <tr>
            <th>Framework Product</th>
            <th>License Type</th>
            <th class="text-right">Price</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td class="td-product">{{ framework_title }}</td>
            <td class="td-license">{{ license_type }}</td>
            <td class="text-right highlight">{{ amount_display }}</td>
          </tr>
        </tbody>
      </table>
      
      <table class="summary-table">
        <tr>
          <td>Subtotal</td>
          <td>{{ amount_display }}</td>
        </tr>
        <tr class="total-row">
          <td>Total Paid</td>
          <td class="highlight">{{ amount_display }}</td>
        </tr>
      </table>
      
      <footer>
        <p>This is a computer-generated document. No manual signature is required.</p>
        <p class="footer-slug">AURACLES &mdash; The Knowledge Marketplace</p>
      </footer>
    </div>
  </body>
</html>
"""
)


def _money_display(amount: Decimal, currency: str) -> str:
    """Return a stable invoice money string."""
    return f"{amount.quantize(Decimal('0.01'))} {currency.upper()}"


def _format_license_type(license_type: str | None) -> str:
    """Format an internal license type string into a readable label."""
    if not license_type:
        return "n/a"
    return license_type.replace("_", " ").title()


def _frontend_url() -> str:
    """Return the frontend base URL."""
    settings = get_settings()
    origins = settings.cors_origin_list
    return origins[0] if origins else "http://localhost:3000"


async def _render_purchase_invoice_pdf(transaction_id: str) -> tuple[str, bytes]:
    """Render a purchase invoice PDF and return its S3 key plus bytes."""
    parsed_transaction_id = UUID(transaction_id)
    async with async_session_factory() as db:
        row = await db.execute(
            select(Transaction, Framework, License, User)
            .join(Framework, Framework.id == Transaction.ref_id)
            .outerjoin(License, License.transaction_id == Transaction.id)
            .join(User, User.id == Transaction.payer_id)
            .where(
                Transaction.id == parsed_transaction_id,
                Transaction.transaction_type == "purchase",
            )
        )
        purchase = row.one_or_none()
        if purchase is None:
            raise ValueError("Purchase transaction not found.")
        transaction, framework, license_row, operator = purchase

    html = INVOICE_TEMPLATE.render(
        transaction_id=str(transaction.id),
        operator_name=operator.display_name,
        operator_email=operator.email,
        framework_title=framework.title,
        license_type=_format_license_type(
            license_row.license_type if license_row else ""
        ),
        amount_display=_money_display(transaction.amount, transaction.currency),
        status=transaction.status,
        logo_url=f"{_frontend_url()}/images/logo-text-black.png",
    )
    pdf_bytes = HTML(string=html).write_pdf()
    return purchase_invoice_key(transaction.id), pdf_bytes


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def generate_invoice_pdf(self: Any, transaction_id: str) -> dict[str, str]:
    """Generate and upload a purchase invoice PDF to private S3."""
    log = logger.bind(
        module="financials",
        action="generate_invoice_pdf",
        task_id=self.request.id,
        transaction_id=transaction_id,
    )
    log.info("task_started")
    try:
        invoice_key, pdf_bytes = run_async(_render_purchase_invoice_pdf(transaction_id))
        settings = get_settings()
        s3.storage.upload_bytes(
            settings.s3_reports_bucket,
            invoice_key,
            pdf_bytes,
            "application/pdf",
        )
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    result = {
        "transaction_id": transaction_id,
        "invoice_key": invoice_key,
        "status": "invoice_generated",
    }
    log.info("task_completed", result=result)
    return result
