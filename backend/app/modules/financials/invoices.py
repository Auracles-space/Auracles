"""Invoice helpers shared by request services and Celery tasks."""

from __future__ import annotations

from uuid import UUID


def purchase_invoice_key(transaction_id: UUID | str) -> str:
    """Return the deterministic private S3 key for a purchase invoice."""
    return f"invoices/purchases/{transaction_id}.pdf"
