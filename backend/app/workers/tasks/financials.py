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
    """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <style>
          body { font-family: sans-serif; color: #111827; }
          h1 { font-size: 28px; margin-bottom: 8px; }
          table { width: 100%; border-collapse: collapse; margin-top: 24px; }
          th, td { border-bottom: 1px solid #d1d5db; padding: 10px; }
          th { text-align: left; background: #f3f4f6; }
          .muted { color: #6b7280; }
          .total { font-weight: 700; }
        </style>
      </head>
      <body>
        <h1>Auracles Invoice</h1>
        <p class="muted">Transaction {{ transaction_id }}</p>
        <p>Bill to: {{ operator_name }} &lt;{{ operator_email }}&gt;</p>
        <table>
          <thead>
            <tr>
              <th>Framework</th>
              <th>License</th>
              <th>Amount</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{{ framework_title }}</td>
              <td>{{ license_type }}</td>
              <td>{{ amount_display }}</td>
            </tr>
          </tbody>
        </table>
        <p class="total">Total paid: {{ amount_display }}</p>
        <p>Status: {{ status }}</p>
      </body>
    </html>
    """
)


def _money_display(amount: Decimal, currency: str) -> str:
    """Return a stable invoice money string."""
    return f"{amount.quantize(Decimal('0.01'))} {currency.upper()}"


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
        license_type=license_row.license_type if license_row else "n/a",
        amount_display=_money_display(transaction.amount, transaction.currency),
        status=transaction.status,
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
