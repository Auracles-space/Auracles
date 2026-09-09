"""Integration tests for the organization purchase-invoice endpoint.

Organizations as Operators: an org admin can retrieve the invoice for a
Framework the organization purchased. The invoice is issued lazily under the
org identity (buyer name = org name, buyer email = the org billing contact,
falling back to the owner) and delivered via a presigned URL once its PDF
exists. This is a billing record available to owner/admins regardless of the
org's operator capability state.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import User
from app.modules.financials import service as financials_service
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework, License
from app.modules.invoicing.models import Invoice, InvoiceCounter
from app.modules.organizations.models import Organization, OrgMember
from app.shared.models.audit_log import AuditLog
from tests.integration.test_organizations_endpoints import (
    add_member,
    auth,
    create_org,
    migrated_database,
)

pytestmark = pytest.mark.asyncio
__all__ = ["migrated_database"]


class FakeInvoiceTask:
    """Celery task double recording invoice generation requests."""

    def __init__(self) -> None:
        """Initialise the in-memory dispatch log."""
        self.dispatched: list[str] = []

    def delay(self, transaction_id: str) -> None:
        """Record the transaction id that would be sent to Celery."""
        self.dispatched.append(transaction_id)


class FakeReportStorage:
    """S3 storage double for invoice existence checks and presigned reads."""

    def __init__(self) -> None:
        """Start with no rendered invoices on file."""
        self.existing: set[str] = set()

    def object_exists(self, bucket: str, key: str) -> bool:
        """Report whether the invoice PDF exists (test-controlled)."""
        del bucket
        return key in self.existing

    def presigned_get(
        self,
        bucket: str,
        key: str,
        expires_in: int,
        *,
        download_name: str | None = None,
    ) -> str:
        """Return a deterministic download URL."""
        return f"https://s3.test/{bucket}/{key}?expires={expires_in}"


async def _create_user(prefix: str) -> UUID:
    """Create one verified user and return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
                kyc_status="verified",
            )
            session.add(user)
            await session.flush()
            return user.id


async def _seed_settled_org_purchase(org_id: UUID) -> tuple[UUID, UUID]:
    """Seed a published Framework and a settled org-payer purchase.

    Returns the transaction id and the seller (contributor) user id.
    """
    contributor_id = await _create_user("org-invoice-seller")
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title="Org Invoice Framework",
                description="Framework purchased by an organization.",
                version="1.0.0",
                status="published",
                category="framework",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["org-invoice"],
                tags_text="org-invoice",
                jurisdiction="gb",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=Decimal("199.00"),
                currency="USD",
                license_types=["team"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            transaction = Transaction(
                payer_id=None,
                payer_org_id=org_id,
                payee_id=contributor_id,
                amount=Decimal("199.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("199.00"),
                transaction_type="purchase",
                status="completed",
                provider="stripe",
                provider_ref="pi_org_invoice_1",
                ref_id=framework.id,
                ref_type="framework",
            )
            session.add(transaction)
            await session.flush()
            session.add(
                License(
                    framework_id=framework.id,
                    operator_id=None,
                    licensee_org_id=org_id,
                    transaction_id=transaction.id,
                    license_type="team",
                    status="active",
                    version_at_grant=framework.version,
                    seats_used=1,
                    seats_total=10,
                )
            )
            return transaction.id, contributor_id


@pytest.fixture
async def org_invoice_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset invoice/purchase rows and patch the storage + invoice task edges."""
    from app.integrations import s3

    fake_storage = FakeReportStorage()
    fake_task = FakeInvoiceTask()
    await engine.dispose()

    async def cleanup() -> None:
        """Delete purchase + invoice rows in dependency order."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(Invoice))
            await session.execute(delete(InvoiceCounter))
            await session.execute(delete(License))
            await session.execute(delete(Transaction))
            await session.execute(delete(Framework))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    original_storage = s3.storage
    s3.storage = fake_storage
    monkeypatch.setattr(financials_service, "generate_invoice_pdf", fake_task)
    try:
        yield {"storage": fake_storage, "task": fake_task}
    finally:
        s3.storage = original_storage
        await cleanup()
        await engine.dispose()


async def test_org_purchase_invoice_issues_under_org_identity_then_returns_url(
    client: AsyncClient,
    migrated_database: None,
    org_invoice_context: dict[str, Any],
) -> None:
    """First call issues an org-buyer invoice (202); once rendered it 302s."""
    del migrated_database
    owner_id = await _create_user("org-invoice-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "org-invoice")
    transaction_id, _ = await _seed_settled_org_purchase(UUID(str(org["id"])))

    pending = await client.get(
        f"/v1/orgs/{org['id']}/financials/purchases/{transaction_id}/invoice",
        headers=auth(owner_token),
    )
    assert pending.status_code == 202
    assert pending.json()["status"] == "generating"
    assert org_invoice_context["task"].dispatched == [str(transaction_id)]

    async with async_session_factory() as session:
        invoice = await session.scalar(
            select(Invoice).where(Invoice.source_ref_id == transaction_id)
        )
        owner = await session.get(User, owner_id)
    assert invoice is not None
    # Buyer is the organization; email falls back to the owner (no billing_email).
    assert invoice.buyer_name == org["name"]
    assert owner is not None
    assert invoice.buyer_email == owner.email

    # Once the PDF exists, the endpoint redirects to a presigned URL.
    org_invoice_context["storage"].existing.add(invoice.s3_key)
    rendered = await client.get(
        f"/v1/orgs/{org['id']}/financials/purchases/{transaction_id}/invoice",
        headers=auth(owner_token),
        follow_redirects=False,
    )
    assert rendered.status_code == 200
    assert invoice.s3_key in rendered.json()["download_url"]


async def test_org_invoices_list_includes_issued_purchase_invoice(
    client: AsyncClient,
    migrated_database: None,
    org_invoice_context: dict[str, Any],
) -> None:
    """An issued org purchase invoice appears in the org invoice list as a purchase."""
    del migrated_database, org_invoice_context
    owner_id = await _create_user("org-invoice-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "org-invoice")
    transaction_id, _ = await _seed_settled_org_purchase(UUID(str(org["id"])))

    issued = await client.get(
        f"/v1/orgs/{org['id']}/financials/purchases/{transaction_id}/invoice",
        headers=auth(owner_token),
    )
    assert issued.status_code == 202

    listing = await client.get(
        f"/v1/orgs/{org['id']}/financials/invoices",
        headers=auth(owner_token),
    )
    assert listing.status_code == 200
    items = listing.json()["invoices"]
    assert len(items) == 1
    assert items[0]["source_ref_id"] == str(transaction_id)
    assert items[0]["direction"] == "purchase"
    assert "buyer_email" not in items[0]


async def test_org_purchase_invoice_prefers_billing_email_when_set(
    client: AsyncClient,
    migrated_database: None,
    org_invoice_context: dict[str, Any],
) -> None:
    """A configured org billing_email addresses the invoice, not the owner."""
    del migrated_database
    owner_id = await _create_user("org-invoice-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "org-invoice")
    async with async_session_factory() as session:
        async with session.begin():
            organization = await session.get(Organization, UUID(str(org["id"])))
            assert organization is not None
            organization.billing_email = "billing@org-invoice.example"
    transaction_id, _ = await _seed_settled_org_purchase(UUID(str(org["id"])))

    response = await client.get(
        f"/v1/orgs/{org['id']}/financials/purchases/{transaction_id}/invoice",
        headers=auth(owner_token),
    )
    assert response.status_code == 202

    async with async_session_factory() as session:
        invoice = await session.scalar(
            select(Invoice).where(Invoice.source_ref_id == transaction_id)
        )
    assert invoice is not None
    assert invoice.buyer_email == "billing@org-invoice.example"


async def test_org_purchase_invoice_rejects_query_token(
    client: AsyncClient,
    migrated_database: None,
    org_invoice_context: dict[str, Any],
) -> None:
    """The invoice route must not authenticate from a URL query parameter.

    The route used to accept ``?token=`` so the browser could navigate to it
    directly, but the value it took was the full session credential. The
    frontend now fetches the presigned URL with a header and navigates to
    storage itself, so a 401 here is the point.
    """
    del migrated_database, org_invoice_context
    owner_id = await _create_user("org-invoice-token-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "org-invoice-token")
    transaction_id, _ = await _seed_settled_org_purchase(UUID(str(org["id"])))

    response = await client.get(
        f"/v1/orgs/{org['id']}/financials/purchases/{transaction_id}/invoice",
        params={"token": owner_token},
    )

    assert response.status_code == 401


async def test_org_purchase_invoice_forbids_non_admin_member(
    client: AsyncClient,
    migrated_database: None,
    org_invoice_context: dict[str, Any],
) -> None:
    """A plain member cannot pull the org's purchase invoice."""
    del migrated_database, org_invoice_context
    owner_id = await _create_user("org-invoice-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "org-invoice")
    member_id = await _create_user("org-invoice-member")
    await add_member(str(org["id"]), member_id, "member")
    transaction_id, _ = await _seed_settled_org_purchase(UUID(str(org["id"])))

    response = await client.get(
        f"/v1/orgs/{org['id']}/financials/purchases/{transaction_id}/invoice",
        headers=auth(create_access_token(member_id, [])),
    )
    assert response.status_code == 403


async def test_org_purchase_invoice_404_for_foreign_transaction(
    client: AsyncClient,
    migrated_database: None,
    org_invoice_context: dict[str, Any],
) -> None:
    """A purchase owned by another org is not retrievable (404)."""
    del migrated_database, org_invoice_context
    owner_id = await _create_user("org-invoice-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "org-invoice")
    other_owner_id = await _create_user("org-invoice-other-owner")
    other_org = await create_org(
        client, create_access_token(other_owner_id, []), "org-invoice-other"
    )
    transaction_id, _ = await _seed_settled_org_purchase(UUID(str(other_org["id"])))

    response = await client.get(
        f"/v1/orgs/{org['id']}/financials/purchases/{transaction_id}/invoice",
        headers=auth(owner_token),
    )
    assert response.status_code == 404
