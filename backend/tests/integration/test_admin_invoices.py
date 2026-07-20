"""Integration tests for the admin invoice oversight endpoint.

Read-only surface: admins list and search issued invoices for reconciliation.
The internal PDF storage key must never appear, and only admins may call it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.invoicing.models import Invoice
from tests.support.db_cleanup import clear_identity_state_async


async def reset_admin_invoice_state() -> None:
    """Remove invoice and identity test data."""
    async with async_session_factory() as session:
        await session.execute(delete(Invoice))
        await clear_identity_state_async(session)
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure invoicing tables exist for admin oversight tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def admin_invoice_context() -> AsyncIterator[None]:
    """Reset auth/invoice state around each test."""
    await engine.dispose()
    await reset_admin_invoice_state()
    try:
        yield
    finally:
        await reset_admin_invoice_state()
        await engine.dispose()


async def _create_admin() -> UUID:
    """Create a verified admin user."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"admin-{uuid4()}@auracles.space",
                password_hash="not-used",
                display_name="Admin",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(user_id=user.id, role="admin", approved_at=datetime.now(UTC))
            )
        return user.id


async def _create_invoice(*, number: str, buyer_email: str, sequence: int) -> UUID:
    """Create one issued invoice row."""
    async with async_session_factory() as session:
        async with session.begin():
            invoice = Invoice(
                series="AUR",
                sequence_year=2026,
                sequence_number=sequence,
                invoice_number=number,
                doc_type="invoice",
                issue_date=datetime.now(UTC),
                currency="USD",
                subtotal=Decimal("100.00"),
                tax_rate=Decimal("0.0000"),
                tax_amount=Decimal("0.00"),
                total=Decimal("100.00"),
                seller_name="Auracles",
                seller_tax_id="TAX-123",
                seller_address="1 Market St",
                buyer_name="Acme Buyer",
                buyer_email=buyer_email,
                source_ref_type="framework",
                source_ref_id=uuid4(),
                s3_key="private/invoices/secret-invoice.pdf",
            )
            session.add(invoice)
            await session.flush()
            return invoice.id


def _auth_headers(user_id: UUID, *, roles: list[str]) -> dict[str, str]:
    """Build bearer auth headers for a user with the given roles."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_admin_lists_invoices_without_s3_key(
    client: AsyncClient,
    migrated_database: None,
    admin_invoice_context: None,
) -> None:
    """Admin sees invoice metadata but never the internal PDF storage key."""
    del migrated_database, admin_invoice_context
    admin_id = await _create_admin()
    invoice_id = await _create_invoice(
        number="AUR-2026-0001", buyer_email="buyer@acme.com", sequence=1
    )

    response = await client.get(
        "/v1/admin/invoices",
        headers=_auth_headers(admin_id, roles=["admin"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["invoice_id"] == str(invoice_id)
    assert item["invoice_number"] == "AUR-2026-0001"
    assert item["total"] == "100.00"
    assert item["buyer_email"] == "buyer@acme.com"
    # PII/internal guard: the PDF storage key must never leak.
    assert "secret-invoice.pdf" not in response.text
    assert "s3_key" not in item


async def test_admin_searches_invoices_by_number(
    client: AsyncClient,
    migrated_database: None,
    admin_invoice_context: None,
) -> None:
    """The query narrows the invoice directory to matching rows."""
    del migrated_database, admin_invoice_context
    admin_id = await _create_admin()
    await _create_invoice(
        number="AUR-2026-0001", buyer_email="a@x.com", sequence=1
    )
    await _create_invoice(
        number="AUR-2026-0002", buyer_email="b@y.com", sequence=2
    )

    response = await client.get(
        "/v1/admin/invoices",
        headers=_auth_headers(admin_id, roles=["admin"]),
        params={"query": "0002"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["invoice_number"] == "AUR-2026-0002"


async def test_non_admin_cannot_list_invoices(
    client: AsyncClient,
    migrated_database: None,
    admin_invoice_context: None,
) -> None:
    """A contributor token is rejected from the invoice directory."""
    del migrated_database, admin_invoice_context
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"contrib-{uuid4()}@auracles.space",
                password_hash="not-used",
                display_name="Contributor",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(
                    user_id=user.id,
                    role="contributor",
                    approved_at=datetime.now(UTC),
                )
            )
            contributor_id = user.id

    response = await client.get(
        "/v1/admin/invoices",
        headers=_auth_headers(contributor_id, roles=["contributor"]),
    )

    assert response.status_code == 403
