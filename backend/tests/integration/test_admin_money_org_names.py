"""Integration tests for organization awareness on the admin money panels.

Slice D of docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md:
the admin payouts, transactions, invoices, and payment-trace screens name the
organizations involved and can be narrowed to one organization. The panels stay
admin-only and never expose payout-account destination details.
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
from sqlalchemy import delete

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import (
    Escrow,
    FinancialEvent,
    Payout,
    PayoutAccount,
    Transaction,
)
from app.modules.invoicing.models import Invoice
from app.modules.organizations.models import Organization
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Remove money and identity test rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(Invoice))
        await session.execute(delete(FinancialEvent))
        await session.execute(delete(Escrow))
        await session.execute(delete(Transaction))
        await session.execute(delete(Payout))
        await session.execute(delete(PayoutAccount))
        await clear_identity_state_async(session)
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure financial, invoicing, and organization tables exist."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def money_context() -> AsyncIterator[None]:
    """Reset money and identity state around each test."""
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


async def _create_user(*, role: str, display_name: str | None = None) -> UUID:
    """Create a verified user holding one role."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{role}-{uuid4()}@auracles.space",
                password_hash="not-used",
                display_name=display_name or role.title(),
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(user_id=user.id, role=role, approved_at=datetime.now(UTC))
            )
        return user.id


async def _create_org(name: str, created_by: UUID) -> UUID:
    """Create an organization row directly."""
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"org-{uuid4().hex[:8]}",
                name=name,
                country="NG",
                created_by=created_by,
            )
            session.add(org)
            await session.flush()
            return org.id


async def _create_payout(
    *, contributor_id: UUID | None = None, org_id: UUID | None = None
) -> UUID:
    """Create a payout to a contributor or an organization."""
    async with async_session_factory() as session:
        async with session.begin():
            account = PayoutAccount(
                user_id=contributor_id,
                org_id=org_id,
                provider="paystack",
                provider_account_id="acct_secret_destination",
                provider_account_lookup_hash=uuid4().hex,
                account_type="express",
                verified_at=datetime.now(UTC),
            )
            session.add(account)
            await session.flush()
            payout = Payout(
                contributor_id=contributor_id,
                org_id=org_id,
                payout_account_id=account.id,
                amount=Decimal("300.00"),
                currency="NGN",
                commission_deducted=Decimal("30.00"),
                net_amount=Decimal("270.00"),
                status="pending",
            )
            session.add(payout)
            await session.flush()
            return payout.id


async def _create_transaction(
    *,
    payer_id: UUID | None = None,
    payer_org_id: UUID | None = None,
    payee_id: UUID | None = None,
    payee_org_id: UUID | None = None,
) -> UUID:
    """Create one completed purchase transaction."""
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_id=payer_id,
                payer_org_id=payer_org_id,
                payee_id=payee_id,
                payee_org_id=payee_org_id,
                amount=Decimal("500.00"),
                currency="NGN",
                platform_commission=Decimal("50.00"),
                net_amount=Decimal("450.00"),
                transaction_type="purchase",
                status="completed",
                provider="paystack",
                provider_ref=f"ref_{uuid4().hex}",
            )
            session.add(transaction)
            await session.flush()
            return transaction.id


async def _create_invoice(*, transaction_id: UUID, sequence: int) -> UUID:
    """Create one issued invoice sourced from a transaction."""
    async with async_session_factory() as session:
        async with session.begin():
            invoice = Invoice(
                series="AUR",
                sequence_year=2026,
                sequence_number=sequence,
                invoice_number=f"AUR-2026-{sequence:05d}",
                doc_type="invoice",
                issue_date=datetime.now(UTC),
                currency="NGN",
                subtotal=Decimal("500.00"),
                tax_rate=Decimal("0.0000"),
                tax_amount=Decimal("0.00"),
                total=Decimal("500.00"),
                seller_name="Seller",
                seller_tax_id="TAX-1",
                seller_address="1 Market St",
                buyer_name="Buyer",
                buyer_email="buyer@auracles.space",
                source_ref_type="transaction",
                source_ref_id=transaction_id,
                s3_key="private/invoices/secret.pdf",
            )
            session.add(invoice)
            await session.flush()
            return invoice.id


def _headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Build bearer auth headers."""
    return {"Authorization": f"Bearer {create_access_token(user_id, roles)}"}


async def test_admin_payouts_name_beneficiaries_and_filter_by_org(
    client: AsyncClient, migrated_database: None, money_context: None
) -> None:
    """Payout rows carry the org or contributor name; `org_id` narrows to one org.

    Payout-account destination identifiers must never appear.
    """
    del migrated_database, money_context
    admin_id = await _create_user(role="admin")
    contributor_id = await _create_user(role="contributor", display_name="Ada Obi")
    acme = await _create_org("Acme Advisory", admin_id)
    other = await _create_org("Other Org", admin_id)
    acme_payout = await _create_payout(org_id=acme)
    await _create_payout(org_id=other)
    contributor_payout = await _create_payout(contributor_id=contributor_id)
    headers = _headers(admin_id, ["admin"])

    everything = await client.get("/v1/admin/payouts", headers=headers)
    filtered = await client.get(
        "/v1/admin/payouts", params={"org_id": str(acme)}, headers=headers
    )

    assert everything.status_code == 200
    names = {
        item["payout_id"]: item["beneficiary_name"]
        for item in everything.json()["items"]
    }
    assert names[str(acme_payout)] == "Acme Advisory"
    assert names[str(contributor_payout)] == "Ada Obi"
    assert "acct_secret_destination" not in everything.text
    assert filtered.status_code == 200
    assert [item["payout_id"] for item in filtered.json()["items"]] == [
        str(acme_payout)
    ]
    assert filtered.json()["total"] == 1


async def test_admin_transactions_name_orgs_and_filter_by_either_side(
    client: AsyncClient, migrated_database: None, money_context: None
) -> None:
    """Transactions name payer and payee orgs; `org_id` matches either side."""
    del migrated_database, money_context
    admin_id = await _create_user(role="admin")
    buyer = await _create_org("Buyer Org", admin_id)
    seller = await _create_org("Seller Org", admin_id)
    unrelated = await _create_org("Unrelated Org", admin_id)
    both = await _create_transaction(payer_org_id=buyer, payee_org_id=seller)
    sold = await _create_transaction(payer_id=admin_id, payee_org_id=seller)
    await _create_transaction(payer_org_id=unrelated, payee_id=admin_id)
    headers = _headers(admin_id, ["admin"])

    filtered = await client.get(
        "/v1/admin/transactions", params={"org_id": str(seller)}, headers=headers
    )

    assert filtered.status_code == 200
    items = {item["transaction_id"]: item for item in filtered.json()["items"]}
    assert set(items) == {str(both), str(sold)}
    assert items[str(both)]["payer_org_name"] == "Buyer Org"
    assert items[str(both)]["payee_org_name"] == "Seller Org"
    assert items[str(sold)]["payer_org_name"] is None
    assert items[str(sold)]["payee_org_name"] == "Seller Org"


async def test_admin_transaction_trace_names_orgs(
    client: AsyncClient, migrated_database: None, money_context: None
) -> None:
    """The single-payment trace carries the payer and payee org names."""
    del migrated_database, money_context
    admin_id = await _create_user(role="admin")
    buyer = await _create_org("Buyer Org", admin_id)
    transaction_id = await _create_transaction(payer_org_id=buyer, payee_id=admin_id)

    response = await client.get(
        f"/v1/admin/transactions/{transaction_id}",
        headers=_headers(admin_id, ["admin"]),
    )

    assert response.status_code == 200
    transaction = response.json()["transaction"]
    assert transaction["payer_org_name"] == "Buyer Org"
    assert transaction["payee_org_name"] is None


async def test_admin_invoices_name_the_organization_and_filter_by_org(
    client: AsyncClient, migrated_database: None, money_context: None
) -> None:
    """Invoices derive their organization from the source transaction."""
    del migrated_database, money_context
    admin_id = await _create_user(role="admin")
    buyer = await _create_org("Buyer Org", admin_id)
    org_invoice = await _create_invoice(
        transaction_id=await _create_transaction(payer_org_id=buyer, payee_id=admin_id),
        sequence=1,
    )
    personal_invoice = await _create_invoice(
        transaction_id=await _create_transaction(payer_id=admin_id),
        sequence=2,
    )
    headers = _headers(admin_id, ["admin"])

    everything = await client.get("/v1/admin/invoices", headers=headers)
    filtered = await client.get(
        "/v1/admin/invoices", params={"org_id": str(buyer)}, headers=headers
    )

    assert everything.status_code == 200
    items = {item["invoice_id"]: item for item in everything.json()["items"]}
    assert items[str(org_invoice)]["organization_id"] == str(buyer)
    assert items[str(org_invoice)]["organization_name"] == "Buyer Org"
    assert items[str(personal_invoice)]["organization_id"] is None
    assert items[str(personal_invoice)]["organization_name"] is None
    assert "secret.pdf" not in everything.text
    assert filtered.status_code == 200
    assert [item["invoice_id"] for item in filtered.json()["items"]] == [
        str(org_invoice)
    ]


async def test_money_panels_org_filter_is_admin_only(
    client: AsyncClient, migrated_database: None, money_context: None
) -> None:
    """A non-admin is refused on every org-filtered money panel."""
    del migrated_database, money_context
    contributor_id = await _create_user(role="contributor")
    org_id = await _create_org("Acme", contributor_id)
    headers = _headers(contributor_id, ["contributor"])

    for path in ("/v1/admin/payouts", "/v1/admin/transactions", "/v1/admin/invoices"):
        response = await client.get(
            path, params={"org_id": str(org_id)}, headers=headers
        )
        assert response.status_code == 403, path
