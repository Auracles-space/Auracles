"""Financial Celery tasks for invoices and future payout processing."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.auth.models import User
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework, License
from app.modules.invoicing import service as invoicing_service
from app.modules.invoicing.render import render_invoice_pdf
from app.workers.async_runner import run_async
from app.workers.celery_app import app


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
        invoice = await invoicing_service.get_invoice(
            db,
            source_ref_type="transaction",
            source_ref_id=transaction.id,
            doc_type=invoicing_service.DOC_SALES_INVOICE,
        )
        if invoice is None:
            raise ValueError("Issued invoice not found.")

    del license_row, operator
    pdf_bytes = render_invoice_pdf(invoice, line_item_label=framework.title)
    return invoice.s3_key, pdf_bytes


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
