"""Invoicing service — gapless invoice issuance over an immutable ledger.

Issues sales invoices (AUR-INV) and earnings statements (AUR-ERN). Numbers are
gapless per ``(series, year)`` via a counter row locked ``FOR UPDATE`` inside
the same transaction as the ``Invoice`` insert, so a rollback never burns a
number.

Maps to: FR-FIN-003.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.financials.models import PlatformConfig
from app.modules.invoicing.keys import invoice_pdf_key
from app.modules.invoicing.models import Invoice, InvoiceCounter

SERIES_SALES = "AUR-INV"
SERIES_EARNINGS = "AUR-ERN"
DOC_SALES_INVOICE = "sales_invoice"
DOC_EARNINGS_STATEMENT = "earnings_statement"
_CENTS = Decimal("0.01")
_RATE = Decimal("0.0001")


@dataclass(frozen=True)
class SellerIdentity:
    """Snapshot of the issuing entity identity."""

    name: str
    tax_id: str
    address: str


def seller_identity(settings: Settings) -> SellerIdentity:
    """Return the configured seller identity block."""
    return SellerIdentity(
        name=settings.invoice_seller_name,
        tax_id=settings.invoice_seller_tax_id,
        address=settings.invoice_seller_address,
    )


async def _tax_rate(db: AsyncSession) -> Decimal:
    """Return the configured invoice tax rate, defaulting to zero."""
    value = await db.scalar(
        select(PlatformConfig.value).where(PlatformConfig.key == "invoice_tax_rate")
    )
    if value is None:
        return Decimal("0")
    return Decimal(value)


async def get_invoice(
    db: AsyncSession,
    *,
    source_ref_type: str,
    source_ref_id: UUID,
    doc_type: str,
) -> Invoice | None:
    """Return the already-issued invoice for one source/doc tuple."""
    result = await db.execute(
        select(Invoice).where(
            Invoice.source_ref_type == source_ref_type,
            Invoice.source_ref_id == source_ref_id,
            Invoice.doc_type == doc_type,
        )
    )
    return result.scalar_one_or_none()


async def issue_invoice(
    db: AsyncSession,
    *,
    doc_type: str,
    series: str,
    source_ref_type: str,
    source_ref_id: UUID,
    currency: str,
    subtotal: Decimal,
    seller: SellerIdentity,
    buyer_name: str,
    buyer_email: str,
    commission_rate: Decimal | None = None,
    net_amount: Decimal | None = None,
) -> Invoice:
    """Idempotently issue a frozen invoice row with a gapless number."""
    existing = await get_invoice(
        db,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
        doc_type=doc_type,
    )
    if existing is not None:
        return existing

    year = datetime.now(UTC).year
    subtotal_value = subtotal.quantize(_CENTS)
    tax_rate = (await _tax_rate(db)).quantize(_RATE)
    tax_amount = (subtotal_value * tax_rate).quantize(_CENTS)
    total = (subtotal_value + tax_amount).quantize(_CENTS)

    await db.execute(
        pg_insert(InvoiceCounter)
        .values(series=series, year=year, last_number=0)
        .on_conflict_do_nothing(index_elements=["series", "year"])
    )
    counter = await db.scalar(
        select(InvoiceCounter)
        .where(InvoiceCounter.series == series, InvoiceCounter.year == year)
        .with_for_update()
    )
    if counter is None:
        raise RuntimeError("Invoice counter row missing after upsert.")

    counter.last_number += 1
    sequence_number = counter.last_number
    invoice_id = uuid4()
    invoice_number = f"{series}-{year}-{sequence_number:06d}"
    invoice = Invoice(
        id=invoice_id,
        series=series,
        sequence_year=year,
        sequence_number=sequence_number,
        invoice_number=invoice_number,
        doc_type=doc_type,
        currency=currency,
        subtotal=subtotal_value,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        total=total,
        commission_rate=(
            commission_rate.quantize(_RATE) if commission_rate is not None else None
        ),
        net_amount=net_amount.quantize(_CENTS) if net_amount is not None else None,
        seller_name=seller.name,
        seller_tax_id=seller.tax_id,
        seller_address=seller.address,
        buyer_name=buyer_name,
        buyer_email=buyer_email,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
        s3_key=invoice_pdf_key(doc_type, invoice_id),
    )
    db.add(invoice)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        async with db.begin():
            existing = await get_invoice(
                db,
                source_ref_type=source_ref_type,
                source_ref_id=source_ref_id,
                doc_type=doc_type,
            )
            if existing is None:
                raise
            return existing
    return invoice
