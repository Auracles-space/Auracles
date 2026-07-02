"""Unit tests for the invoicing ledger allocator (Module 6d)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import uuid4

import pytest
from freezegun import freeze_time
from sqlalchemy import delete

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.modules.financials.models import PlatformConfig
from app.modules.invoicing import service as invoicing
from app.modules.invoicing.models import Invoice, InvoiceCounter

pytestmark = pytest.mark.asyncio


async def _reset_invoicing_state() -> None:
    """Delete issued invoices and counters in dependency order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(Invoice))
            await session.execute(delete(InvoiceCounter))
            await session.execute(
                delete(PlatformConfig).where(PlatformConfig.key == "invoice_tax_rate")
            )


@pytest.fixture
async def clean_invoicing(migrated_database) -> AsyncIterator[None]:
    """Start each test from an empty invoicing ledger."""
    del migrated_database
    await engine.dispose()
    await _reset_invoicing_state()
    try:
        yield
    finally:
        await _reset_invoicing_state()
        await engine.dispose()


def _seller() -> invoicing.SellerIdentity:
    """Return the configured seller snapshot for invoice issuance."""
    return invoicing.seller_identity(get_settings())


async def _set_platform_config(*, key: str, value: str) -> None:
    """Upsert one platform-config row used by invoicing tests."""
    async with async_session_factory() as session:
        async with session.begin():
            existing = await session.get(PlatformConfig, key)
            if existing is None:
                session.add(PlatformConfig(key=key, value=value))
            else:
                existing.value = value


@freeze_time("2026-05-01")
async def test_first_issue_allocates_number_one(clean_invoicing) -> None:
    """First issued sales invoice in 2026 is AUR-INV-2026-000001."""
    del clean_invoicing
    source_ref_id = uuid4()

    async with async_session_factory() as session:
        invoice = await invoicing.issue_invoice(
            session,
            doc_type=invoicing.DOC_SALES_INVOICE,
            series=invoicing.SERIES_SALES,
            source_ref_type="transaction",
            source_ref_id=source_ref_id,
            currency="USD",
            subtotal=Decimal("500.00"),
            seller=_seller(),
            buyer_name="Ada Op",
            buyer_email="ada@example.com",
        )
        await session.commit()

    assert invoice.sequence_number == 1
    assert invoice.invoice_number == "AUR-INV-2026-000001"
    assert invoice.total == Decimal("500.00")
    assert invoice.s3_key == f"invoices/sales_invoice/{invoice.id}.pdf"


@freeze_time("2026-05-01")
async def test_second_issue_is_gapless_consecutive(clean_invoicing) -> None:
    """Two issues in the same series/year get consecutive numbers."""
    del clean_invoicing

    async with async_session_factory() as session:
        first = await invoicing.issue_invoice(
            session,
            doc_type=invoicing.DOC_SALES_INVOICE,
            series=invoicing.SERIES_SALES,
            source_ref_type="transaction",
            source_ref_id=uuid4(),
            currency="USD",
            subtotal=Decimal("100.00"),
            seller=_seller(),
            buyer_name="A",
            buyer_email="a@example.com",
        )
        second = await invoicing.issue_invoice(
            session,
            doc_type=invoicing.DOC_SALES_INVOICE,
            series=invoicing.SERIES_SALES,
            source_ref_type="transaction",
            source_ref_id=uuid4(),
            currency="USD",
            subtotal=Decimal("100.00"),
            seller=_seller(),
            buyer_name="B",
            buyer_email="b@example.com",
        )
        await session.commit()

    assert (first.sequence_number, second.sequence_number) == (1, 2)


@freeze_time("2026-05-01")
async def test_issue_is_idempotent_per_source_doc(clean_invoicing) -> None:
    """Re-issuing the same source/doc returns the same row."""
    del clean_invoicing
    source_ref_id = uuid4()

    async with async_session_factory() as session:
        first = await invoicing.issue_invoice(
            session,
            doc_type=invoicing.DOC_SALES_INVOICE,
            series=invoicing.SERIES_SALES,
            source_ref_type="attestation",
            source_ref_id=source_ref_id,
            currency="USD",
            subtotal=Decimal("500.00"),
            seller=_seller(),
            buyer_name="A",
            buyer_email="a@example.com",
        )
        await session.commit()

    async with async_session_factory() as session:
        second = await invoicing.issue_invoice(
            session,
            doc_type=invoicing.DOC_SALES_INVOICE,
            series=invoicing.SERIES_SALES,
            source_ref_type="attestation",
            source_ref_id=source_ref_id,
            currency="USD",
            subtotal=Decimal("500.00"),
            seller=_seller(),
            buyer_name="A",
            buyer_email="a@example.com",
        )
        await session.commit()

    assert first.id == second.id
    assert first.invoice_number == second.invoice_number


async def test_rollback_does_not_burn_a_number(clean_invoicing) -> None:
    """A rolled-back insert leaves the next number unconsumed."""
    del clean_invoicing

    with freeze_time("2026-05-01"):
        async with async_session_factory() as session:
            await invoicing.issue_invoice(
                session,
                doc_type=invoicing.DOC_SALES_INVOICE,
                series=invoicing.SERIES_SALES,
                source_ref_type="transaction",
                source_ref_id=uuid4(),
                currency="USD",
                subtotal=Decimal("100.00"),
                seller=_seller(),
                buyer_name="A",
                buyer_email="a@example.com",
            )
            await session.rollback()

        async with async_session_factory() as session:
            kept = await invoicing.issue_invoice(
                session,
                doc_type=invoicing.DOC_SALES_INVOICE,
                series=invoicing.SERIES_SALES,
                source_ref_type="transaction",
                source_ref_id=uuid4(),
                currency="USD",
                subtotal=Decimal("100.00"),
                seller=_seller(),
                buyer_name="A",
                buyer_email="a@example.com",
            )
            await session.commit()

    assert kept.sequence_number == 1


async def test_number_resets_per_year(clean_invoicing) -> None:
    """A new calendar year restarts the sequence at one."""
    del clean_invoicing

    with freeze_time("2026-12-31"):
        async with async_session_factory() as session:
            invoice_2026 = await invoicing.issue_invoice(
                session,
                doc_type=invoicing.DOC_SALES_INVOICE,
                series=invoicing.SERIES_SALES,
                source_ref_type="transaction",
                source_ref_id=uuid4(),
                currency="USD",
                subtotal=Decimal("100.00"),
                seller=_seller(),
                buyer_name="A",
                buyer_email="a@example.com",
            )
            await session.commit()

    with freeze_time("2027-01-01"):
        async with async_session_factory() as session:
            invoice_2027 = await invoicing.issue_invoice(
                session,
                doc_type=invoicing.DOC_SALES_INVOICE,
                series=invoicing.SERIES_SALES,
                source_ref_type="transaction",
                source_ref_id=uuid4(),
                currency="USD",
                subtotal=Decimal("100.00"),
                seller=_seller(),
                buyer_name="A",
                buyer_email="a@example.com",
            )
            await session.commit()

    assert invoice_2026.invoice_number == "AUR-INV-2026-000001"
    assert invoice_2027.invoice_number == "AUR-INV-2027-000001"


@freeze_time("2026-05-01")
async def test_tax_line_uses_platform_config_snapshot(clean_invoicing) -> None:
    """Configured invoice tax rate is applied and snapshotted."""
    del clean_invoicing
    await _set_platform_config(key="invoice_tax_rate", value="0.075")

    async with async_session_factory() as session:
        invoice = await invoicing.issue_invoice(
            session,
            doc_type=invoicing.DOC_SALES_INVOICE,
            series=invoicing.SERIES_SALES,
            source_ref_type="transaction",
            source_ref_id=uuid4(),
            currency="USD",
            subtotal=Decimal("500.00"),
            seller=_seller(),
            buyer_name="Taxed Buyer",
            buyer_email="taxed@example.com",
        )
        await session.commit()

    assert invoice.tax_rate == Decimal("0.0750")
    assert invoice.tax_amount == Decimal("37.50")
    assert invoice.total == Decimal("537.50")


@freeze_time("2026-05-01")
async def test_earnings_statement_snapshots_rate_and_net(clean_invoicing) -> None:
    """Earnings statements store commission rate and net remittance."""
    del clean_invoicing

    async with async_session_factory() as session:
        invoice = await invoicing.issue_invoice(
            session,
            doc_type=invoicing.DOC_EARNINGS_STATEMENT,
            series=invoicing.SERIES_EARNINGS,
            source_ref_type="attestation",
            source_ref_id=uuid4(),
            currency="USD",
            subtotal=Decimal("500.00"),
            seller=_seller(),
            buyer_name="Expert Attestor",
            buyer_email="expert@example.com",
            commission_rate=Decimal("0.1000"),
            net_amount=Decimal("450.00"),
        )
        await session.commit()

    assert invoice.commission_rate == Decimal("0.1000")
    assert invoice.net_amount == Decimal("450.00")
