"""Deterministic S3 keys for issued invoice documents."""

from __future__ import annotations

from uuid import UUID


def invoice_pdf_key(doc_type: str, invoice_id: UUID) -> str:
    """Return the private S3 key for an issued invoice PDF."""
    return f"invoices/{doc_type}/{invoice_id}.pdf"
