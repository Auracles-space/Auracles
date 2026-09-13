"""Integration tests for org contributor financials and shared legal identity.

Exercises the contributor-capability path on the existing org financial routes
plus the new owner-managed shared legal-profile endpoints.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.financials.models import Payout, PayoutAccount, Transaction
from app.modules.invoicing.models import Invoice
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgLegalProfile,
    OrgMember,
)
from app.shared.models.audit_log import AuditLog
from tests.conftest import open_step_up_window
from tests.integration.test_auth_sessions import FakeRedis
from tests.integration.test_organizations_endpoints import (
    add_member,
    auth,
    create_org,
    migrated_database,
)
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio
__all__ = ["migrated_database"]


@pytest.fixture
async def clean_state() -> AsyncIterator[FakeRedis]:
    """Reset org contributor financial rows and install fake Redis."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete financial, org, and identity rows in FK-safe order."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(Invoice))
            await session.execute(delete(Payout))
            await session.execute(delete(PayoutAccount))
            await session.execute(delete(Transaction))
            await session.execute(delete(OrgLegalProfile))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await clear_identity_state_async(session)
            await session.commit()

    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    await cleanup()
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def _create_user(
    prefix: str,
    *,
    totp_secret: str | None = None,
) -> UUID:
    """Create one verified user and return its id."""
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
                totp_enabled=totp_secret is not None,
                totp_secret=(
                    encrypt_totp_secret(totp_secret)
                    if totp_secret is not None
                    else None
                ),
            )
            session.add(user)
            await session.flush()
            return user.id


async def _seed_contributor_org_financial_rows(
    *,
    org_id: UUID,
    owner_id: UUID,
    include_tax_document: bool,
) -> tuple[UUID, UUID]:
    """Seed contributor org earnings, payout account, and one issued invoice."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=org_id,
                    capability="contributor",
                    status="active",
                )
            )
            # create_org already made a verified legal profile (an unverified
            # org is a shell), so this seeder shapes that row rather than
            # colliding with the one-per-org constraint.
            profile = await session.scalar(
                select(OrgLegalProfile).where(OrgLegalProfile.org_id == org_id)
            )
            assert profile is not None
            profile.legal_name = "Shared Legal Name LLC"
            profile.registration_number = "RC-123456"
            profile.address = {"country": "US", "city": "New York"}
            profile.tax_document_type = "w9" if include_tax_document else None
            profile.tax_document_key = (
                "org-legal-profiles/tax-doc.pdf" if include_tax_document else None
            )
            payout_account = PayoutAccount(
                org_id=org_id,
                provider="stripe",
                provider_account_id="acct_shared_legal",
                provider_account_lookup_hash="acct_shared_legal_hash",
                account_type="express",
                is_default=True,
                verified_at=datetime.now(UTC),
            )
            session.add(payout_account)
            transaction = Transaction(
                payer_id=owner_id,
                payee_id=None,
                payee_org_id=org_id,
                amount=Decimal("1000.00"),
                currency="USD",
                # Stamped at the 15% marketplace rate, as settlement writes it.
                platform_commission=Decimal("150.00"),
                net_amount=Decimal("850.00"),
                transaction_type="purchase",
                status="completed",
                provider="stripe",
                provider_ref=f"pi_{uuid4().hex}",
                ref_id=uuid4(),
                ref_type="framework",
                created_at=datetime.now(UTC) - timedelta(hours=72),
            )
            session.add(transaction)
            await session.flush()
            invoice = Invoice(
                series="AUR-INV",
                sequence_year=2026,
                sequence_number=1,
                invoice_number="AUR-INV-2026-000001",
                doc_type="sales_invoice",
                currency="USD",
                subtotal=Decimal("1000.00"),
                tax_rate=Decimal("0.0000"),
                tax_amount=Decimal("0.00"),
                total=Decimal("1000.00"),
                seller_name="Shared Legal Name LLC",
                seller_tax_id="RC-123456",
                seller_address="New York, US",
                buyer_name="Buyer Name",
                buyer_email="buyer@example.com",
                source_ref_type="transaction",
                source_ref_id=transaction.id,
                s3_key=f"invoices/sales_invoice/{transaction.id}.pdf",
            )
            session.add(invoice)
            await session.flush()
            return payout_account.id, transaction.id


async def test_owner_can_upsert_and_read_shared_legal_profile(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
) -> None:
    """The org owner can PUT then GET the shared legal profile."""
    del migrated_database
    owner_secret = pyotp.random_base32()
    owner_id = await _create_user("org-owner", totp_secret=owner_secret)
    owner_token = create_access_token(owner_id, [])
    await open_step_up_window(clean_state, owner_id)
    # Pre-verification: identity fields are still ordinary data entry. Once
    # verified they lock, which is its own test below.
    org = await create_org(client, owner_token, "org-legal-profile", verified=False)

    updated = await client.put(
        f"/v1/orgs/{org['id']}/legal-profile",
        headers=auth(owner_token),
        json={
            "legal_name": "Shared Legal Name LLC",
            "registration_number": "RC-123456",
            "address": {"country": "US", "city": "New York"},
        },
    )

    assert updated.status_code == 200
    assert updated.json()["legal_name"] == "Shared Legal Name LLC"
    assert "tax_document_key" not in updated.json()

    fetched = await client.get(
        f"/v1/orgs/{org['id']}/legal-profile",
        headers=auth(owner_token),
    )

    assert fetched.status_code == 200
    assert fetched.json()["registration_number"] == "RC-123456"
    assert fetched.json()["address"] == {"country": "US", "city": "New York"}


async def test_verified_identity_cannot_be_renamed(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
) -> None:
    """A verified org cannot change the name an admin verified.

    Without this, the owner could verify as one entity, rename to another, and
    keep the badge — on a platform whose product is provenance. Non-identity
    fields (address) stay editable: they are invoice data, not what the
    reviewer checked.
    """
    del migrated_database
    owner_secret = pyotp.random_base32()
    owner_id = await _create_user("org-owner-lock", totp_secret=owner_secret)
    owner_token = create_access_token(owner_id, [])
    await open_step_up_window(clean_state, owner_id)
    org = await create_org(client, owner_token, "org-legal-lock")

    renamed = await client.put(
        f"/v1/orgs/{org['id']}/legal-profile",
        headers=auth(owner_token),
        json={
            "legal_name": "Entirely Different Entity Ltd",
            "registration_number": "RC-999999",
        },
    )
    assert renamed.status_code == 409

    address_only = await client.put(
        f"/v1/orgs/{org['id']}/legal-profile",
        headers=auth(owner_token),
        json={
            "legal_name": "Verified Test Org Ltd",
            "registration_number": "RC000000",
            "address": {"country": "NG", "city": "Lagos"},
        },
    )
    assert address_only.status_code == 200
    assert address_only.json()["address"] == {"country": "NG", "city": "Lagos"}


async def test_legal_profile_endpoints_require_owner_and_step_up(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
) -> None:
    """Legal profile reads are owner-only and writes need an open step-up window."""
    del migrated_database
    owner_secret = pyotp.random_base32()
    owner_id = await _create_user("org-owner", totp_secret=owner_secret)
    admin_id = await _create_user("org-admin")
    owner_token = create_access_token(owner_id, [])
    admin_token = create_access_token(admin_id, [])
    org = await create_org(client, owner_token, "org-legal-guard")
    await add_member(str(org["id"]), admin_id, "admin")

    unauth = await client.get(f"/v1/orgs/{org['id']}/legal-profile")
    assert unauth.status_code == 401

    forbidden = await client.get(
        f"/v1/orgs/{org['id']}/legal-profile",
        headers=auth(admin_token),
    )
    assert forbidden.status_code == 403

    no_window = await client.put(
        f"/v1/orgs/{org['id']}/legal-profile",
        headers=auth(owner_token),
        json={
            "legal_name": "Shared Legal Name LLC",
            "registration_number": "RC-123456",
            "address": {"country": "US", "city": "New York"},
        },
    )
    assert no_window.status_code == 403
    assert no_window.json()["detail"]["error_code"] == "step_up_required"


async def test_owner_can_create_legal_profile_tax_document_upload_session(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
) -> None:
    """The org owner can create a presigned upload session for the tax document."""
    del migrated_database
    owner_secret = pyotp.random_base32()
    owner_id = await _create_user("org-owner", totp_secret=owner_secret)
    owner_token = create_access_token(owner_id, [])
    await open_step_up_window(clean_state, owner_id)
    # Identity is entered before verification; once verified it locks, and
    # this test is about the tax-document session, not the lock.
    org = await create_org(client, owner_token, "org-legal-tax-doc", verified=False)

    updated = await client.put(
        f"/v1/orgs/{org['id']}/legal-profile",
        headers=auth(owner_token),
        json={
            "legal_name": "Shared Legal Name LLC",
            "registration_number": "RC-123456",
            "address": {"country": "US", "city": "New York"},
        },
    )
    assert updated.status_code == 200

    upload = await client.post(
        f"/v1/orgs/{org['id']}/legal-profile/tax-document",
        headers=auth(owner_token),
        json={
            "tax_document_type": "w9",
            "file_name": "w9.pdf",
            "content_type": "application/pdf",
            "size_bytes": 1024,
        },
    )

    assert upload.status_code == 200
    body = upload.json()
    assert body["scan_status"] == "pending_scan"
    assert body["s3_key"].startswith(f"org-legal-profiles/{org['id']}/tax-documents/")


async def test_contributor_org_financial_routes_use_shared_identity_and_hide_pii(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contributor org earnings, invoices, and payout reuse org financial routes."""
    del migrated_database
    fake_task = SimpleNamespace(dispatched=[])

    def _delay(payout_id: str) -> None:
        fake_task.dispatched.append(payout_id)

    fake_task.delay = _delay
    from app.modules.financials import service as financials_service

    monkeypatch.setattr(financials_service, "process_payout", fake_task, raising=False)

    owner_secret = pyotp.random_base32()
    owner_id = await _create_user("org-owner", totp_secret=owner_secret)
    owner_token = create_access_token(owner_id, [])
    await open_step_up_window(clean_state, owner_id)
    org = await create_org(client, owner_token, "org-contributor-financials")
    payout_account_id, transaction_id = await _seed_contributor_org_financial_rows(
        org_id=UUID(str(org["id"])),
        owner_id=owner_id,
        include_tax_document=True,
    )

    earnings = await client.get(
        f"/v1/orgs/{org['id']}/financials/earnings",
        headers=auth(owner_token),
    )
    assert earnings.status_code == 200
    assert Decimal(str(earnings.json()["gross_revenue"])) == Decimal("1000.00")
    assert Decimal(str(earnings.json()["available_balance"])) == Decimal("850.00")

    invoices = await client.get(
        f"/v1/orgs/{org['id']}/financials/invoices",
        headers=auth(owner_token),
    )
    assert invoices.status_code == 200
    items = invoices.json()["invoices"]
    assert len(items) == 1
    assert items[0]["source_ref_type"] == "transaction"
    assert items[0]["source_ref_id"] == str(transaction_id)
    assert "buyer_email" not in items[0]
    assert "seller_tax_id" not in items[0]
    assert "provider_account_ref" not in items[0]

    payout = await client.post(
        f"/v1/orgs/{org['id']}/financials/payouts",
        headers=auth(owner_token),
        json={
            "amount": "100.00",
            "currency": "USD",
            "payout_account_id": str(payout_account_id),
        },
    )
    assert payout.status_code == 200

    async with async_session_factory() as session:
        payout_row = await session.scalar(select(Payout))

    assert payout_row is not None
    assert payout_row.org_id == UUID(str(org["id"]))
    assert payout_row.contributor_id is None
    assert fake_task.dispatched == [str(payout_row.id)]


async def test_contributor_org_payout_requires_tax_document(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
) -> None:
    """Contributor org payouts are blocked until the shared tax document exists."""
    del migrated_database
    owner_secret = pyotp.random_base32()
    owner_id = await _create_user("org-owner", totp_secret=owner_secret)
    owner_token = create_access_token(owner_id, [])
    await open_step_up_window(clean_state, owner_id)
    org = await create_org(client, owner_token, "org-contributor-no-tax")
    payout_account_id, _transaction_id = await _seed_contributor_org_financial_rows(
        org_id=UUID(str(org["id"])),
        owner_id=owner_id,
        include_tax_document=False,
    )

    payout = await client.post(
        f"/v1/orgs/{org['id']}/financials/payouts",
        headers=auth(owner_token),
        json={
            "amount": "100.00",
            "currency": "USD",
            "payout_account_id": str(payout_account_id),
        },
    )

    assert payout.status_code == 403
