"""Celery tasks for shared invoice document generation."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.attestation.models import Attestation
from app.modules.frameworks.models import Framework
from app.modules.invoicing.models import Invoice
from app.modules.invoicing.render import render_invoice_pdf
from app.workers.async_runner import run_async
from app.workers.celery_app import app


def _review_type_label(attestation: Attestation) -> str:
    """Return a human display label for one attestation review type."""
    labels = {
        "quality": "Quality Attestation",
        "compliance": "Compliance Attestation",
        "expert": "Expert Attestation",
        "provenance": "Provenance Attestation",
    }
    return labels.get(attestation.review_type or "", "Attestation")


async def _generate_invoice_document(invoice_id: str) -> tuple[str, bytes]:
    """Load one issued invoice and render its PDF bytes."""
    parsed_invoice_id = UUID(invoice_id)
    async with async_session_factory() as db:
        invoice = await db.get(Invoice, parsed_invoice_id)
        if invoice is None:
            raise ValueError("Issued invoice not found.")

        if invoice.source_ref_type == "attestation":
            attestation = await db.get(Attestation, invoice.source_ref_id)
            if attestation is None:
                raise ValueError("Attestation source not found.")
            line_item_label = _review_type_label(attestation)
        elif invoice.source_ref_type == "transaction":
            framework_title = await db.scalar(
                select(Framework.title).where(Framework.id == invoice.source_ref_id)
            )
            if framework_title is None:
                raise ValueError("Framework source not found.")
            line_item_label = framework_title
        else:
            raise ValueError(
                f"Unsupported invoice source_ref_type: {invoice.source_ref_type}"
            )

    pdf_bytes = render_invoice_pdf(invoice, line_item_label=line_item_label)
    return invoice.s3_key, pdf_bytes


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def generate_invoice_document(self: Any, invoice_id: str) -> dict[str, str]:
    """Generate and upload one invoice or earnings-statement PDF."""
    log = logger.bind(
        module="invoicing",
        action="generate_invoice_document",
        task_id=self.request.id,
        invoice_id=invoice_id,
    )
    log.info("task_started")
    try:
        invoice_key, pdf_bytes = run_async(_generate_invoice_document(invoice_id))
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
        "invoice_id": invoice_id,
        "invoice_key": invoice_key,
        "status": "invoice_generated",
    }
    log.info("task_completed", result=result)
    return result
