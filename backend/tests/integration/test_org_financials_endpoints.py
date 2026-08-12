"""Integration tests for org-as-Attestor settlement, payout, and invoicing.

Released attestation fees are credited to the attestor organization
(``payee_org_id``) at settlement, org owners/admins draw the balance down via a
TOTP-gated org payout (gated on an approved attestor application), and invoices
bill to the org's legal identity. Enforces the settlement/financials re-point of
docs/superpowers/specs/2026-07-04-org-attestor-design.md (Task 8).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import (
    create_access_token,
    encrypt_payout_provider_account_id,
    encrypt_totp_secret,
    hash_password,
    hash_payout_provider_account_id,
)
from app.modules.attestation import document_service, release_service
from app.modules.attestation.models import Attestation
from app.modules.auth.models import User
from app.modules.financials import service as financials_service
from app.modules.financials.models import Escrow, Payout, PayoutAccount, Transaction
from app.modules.invoicing.models import Invoice, InvoiceCounter
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgAttestorProfile,
    OrgCapability,
    OrgMember,
    OrgMemberNda,
)
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio

NDA_VERSION = get_settings().org_member_nda_version


async def _reset_state() -> None:
    """Clear financial, invoice, and org rows in FK-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AuditLog))
            await session.execute(delete(Invoice))
            await session.execute(delete(InvoiceCounter))
            await session.execute(delete(Payout))
            await session.execute(delete(Attestation))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(PayoutAccount))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgAttestorApplication))
            await session.execute(delete(OrgMemberNda))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(User))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the integration database is upgraded to alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database: None) -> AsyncIterator[None]:
    """Reset financial state before and after each test."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


@pytest.fixture
async def db_session(clean_state: None) -> AsyncIterator:
    """Provide an async session for service-level tests."""
    del clean_state
    async with async_session_factory() as session:
        yield session


class _FakePayoutTask:
    """Record dispatched payout ids in place of the Celery task."""

    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def delay(self, payout_id: str) -> None:
        """Capture a dispatched payout id."""
        self.dispatched.append(payout_id)


def _auth(user_id: UUID) -> dict[str, str]:
    """Build bearer auth headers for one user."""
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id, roles=[])}"}


async def _new_user(prefix: str, *, totp: bool = False) -> tuple[UUID, str | None]:
    """Create a verified user; return (id, totp_secret)."""
    secret = pyotp.random_base32() if totp else None
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
                totp_enabled=totp,
                totp_secret=encrypt_totp_secret(secret) if secret else None,
            )
            session.add(user)
            await session.flush()
            return user.id, secret


async def _attestor_org(
    *,
    approved: bool = True,
    legal_name: str | None = "Attestor Org LLC",
    country: str = "US",
) -> tuple[UUID, UUID, str]:
    """Create an attestor org with a TOTP owner. Return (org_id, owner_id, secret)."""
    owner_id, secret = await _new_user("owner", totp=True)
    assert secret is not None
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"org-{uuid4().hex[:6]}",
                name="Attestor Org",
                country=country,
                created_by=owner_id,
            )
            session.add(org)
            await session.flush()
            member = OrgMember(org_id=org.id, user_id=owner_id, role="owner")
            session.add(member)
            await session.flush()
            session.add(OrgMemberNda(member_id=member.id, nda_version=NDA_VERSION))
            session.add(
                OrgCapability(org_id=org.id, capability="attestor", status="active")
            )
            session.add(
                OrgAttestorProfile(
                    org_id=org.id,
                    specializations=["tax"],
                    jurisdictions=["US"],
                    sectors=["tax"],
                    functions=[],
                    active=True,
                    approved_at=now,
                    coi_signed_at=now,
                    coi_expires_at=now + timedelta(days=365),
                )
            )
            session.add(
                OrgAttestorApplication(
                    org_id=org.id,
                    status="approved" if approved else "submitted",
                    legal_name=legal_name,
                    specializations=["tax"],
                    jurisdictions=["US"],
                    sectors=["tax"],
                    credentials_summary="Chartered tax reviewers.",
                    sample_work={},
                    professional_references="Available on request.",
                )
            )
            return org.id, owner_id, secret


async def _add_member(org_id: UUID, *, role: str = "member") -> tuple[UUID, UUID]:
    """Add a member to an org. Return (member_id, user_id)."""
    user_id, _ = await _new_user(role)
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=org_id, user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            session.add(OrgMemberNda(member_id=member.id, nda_version=NDA_VERSION))
            return member.id, user_id


async def _org_payout_account(org_id: UUID, *, verified: bool = True) -> UUID:
    """Create an org-owned payout account. Return its id."""
    provider_account_id = f"acct_{uuid4()}"
    async with async_session_factory() as session:
        async with session.begin():
            account = PayoutAccount(
                org_id=org_id,
                provider="stripe",
                provider_account_id=encrypt_payout_provider_account_id(
                    provider_account_id
                ),
                provider_account_lookup_hash=hash_payout_provider_account_id(
                    provider_account_id
                ),
                account_type="express",
                is_default=True,
                verified_at=datetime.now(UTC) if verified else None,
            )
            session.add(account)
            await session.flush()
            return account.id


async def _org_attestation_report_submitted(
    org_id: UUID,
    reviewing_member_id: UUID,
    *,
    fee: Decimal = Decimal("500.00"),
) -> tuple[UUID, UUID]:
    """Seed a report-submitted org attestation with a held fee escrow.

    Returns (requestor_id, attestation_id). The fee transaction carries no
    payee yet — settlement is where the org is credited.
    """
    requestor_id, _ = await _new_user("requestor")
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="contributor",
                target_id=uuid4(),
                requestor_id=requestor_id,
                attestor_org_id=org_id,
                reviewing_member_id=reviewing_member_id,
                status="report_submitted",
                outcome="approved",
                review_type="quality",
                fee_amount=fee,
                currency="USD",
                requested_specializations=["tax"],
                requested_jurisdictions=["US"],
                summary="Reviewed evidence supports approval.",
                scope="Contributor credential review.",
                evidence_references={},
                report_key=f"attestation-reports/{uuid4()}/report.pdf",
                accepted_at=now - timedelta(days=1),
                completion_due_at=now + timedelta(days=6),
                issued_at=now - timedelta(hours=1),
                dispute_window_ends_at=now + timedelta(days=14),
            )
            session.add(attestation)
            await session.flush()
            transaction = Transaction(
                payer_id=requestor_id,
                payee_id=None,
                payee_org_id=None,
                amount=fee,
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=fee,
                transaction_type="attestation_fee",
                status="completed",
                provider="stripe",
                provider_ref=f"pi_{uuid4().hex}",
                ref_id=attestation.id,
                ref_type="attestation",
            )
            session.add(transaction)
            await session.flush()
            escrow = Escrow(
                ref_id=attestation.id,
                ref_type="attestation",
                amount=fee,
                currency="USD",
                status="held",
                release_conditions={"kind": "attestation"},
                transaction_id=transaction.id,
            )
            session.add(escrow)
            await session.flush()
            attestation.escrow_id = escrow.id
            return requestor_id, attestation.id


async def _release(requestor_id: UUID, attestation_id: UUID) -> None:
    """Accept the report, settling escrow to the org."""
    async with async_session_factory() as session:
        requestor = await session.get(User, requestor_id)
        assert requestor is not None
        await release_service.accept_report(
            db=session,
            requestor=requestor,
            attestation_id=attestation_id,
        )


# --- Settlement -----------------------------------------------------------


async def test_release_credits_org_beneficiary(db_session) -> None:
    """Settling an org attestation credits payee_org_id, never payee_id."""
    del db_session
    org_id, _owner, _secret = await _attestor_org()
    member_id, _ = await _add_member(org_id)
    requestor_id, attestation_id = await _org_attestation_report_submitted(
        org_id, member_id
    )

    await _release(requestor_id, attestation_id)

    async with async_session_factory() as session:
        transaction = await session.scalar(
            select(Transaction).where(Transaction.ref_id == attestation_id)
        )
        escrow = await session.scalar(
            select(Escrow).where(Escrow.ref_id == attestation_id)
        )
    assert transaction is not None
    assert transaction.payee_org_id == org_id
    assert transaction.payee_id is None
    assert escrow is not None
    assert escrow.status == "released"


async def test_org_earnings_reflect_released_fee(db_session) -> None:
    """Released fees appear as available org earnings net of commission."""
    org_id, _owner, _secret = await _attestor_org()
    member_id, _ = await _add_member(org_id)
    requestor_id, attestation_id = await _org_attestation_report_submitted(
        org_id, member_id
    )
    await _release(requestor_id, attestation_id)

    earnings = await financials_service.get_org_earnings(db_session, org_id=org_id)

    # 500 gross, 10% attestation commission -> 450 net available immediately.
    assert earnings.gross_revenue == Decimal("500.00")
    assert earnings.pending_clearance == Decimal("0.00")
    assert earnings.available_balance == Decimal("450.00")


async def test_annual_org_summary_helpers(db_session) -> None:
    """The annual beat sees an org's settled work under its org identity."""
    from datetime import datetime as _dt

    from app.modules.invoicing import annual

    org_id, _owner, _secret = await _attestor_org(legal_name="Attestor Org LLC")
    member_id, _ = await _add_member(org_id)
    requestor_id, attestation_id = await _org_attestation_report_submitted(
        org_id, member_id
    )
    await _release(requestor_id, attestation_id)
    year = _dt.now(UTC).year

    earner_ids = await annual.annual_org_earner_ids(db_session, year)
    line_items, totals = await annual.annual_org_line_items(
        db_session, org_id=org_id, year=year
    )
    name = await annual.org_name(db_session, org_id)

    assert org_id in earner_ids
    assert totals["count"] == 1
    assert line_items[0]["attestation_id"] == str(attestation_id)
    assert name == "Attestor Org LLC"


async def test_unreleased_fee_is_not_org_earnings(db_session) -> None:
    """A held (unreleased) org fee contributes no available balance."""
    org_id, _owner, _secret = await _attestor_org()
    member_id, _ = await _add_member(org_id)
    await _org_attestation_report_submitted(org_id, member_id)

    earnings = await financials_service.get_org_earnings(db_session, org_id=org_id)

    assert earnings.available_balance == Decimal("0.00")


# --- Org payout -----------------------------------------------------------


async def test_request_org_payout_requires_approved_application(db_session) -> None:
    """An org without an approved attestor application cannot request payout."""
    org_id, owner_id, secret = await _attestor_org(approved=False)
    member_id, _ = await _add_member(org_id)
    requestor_id, attestation_id = await _org_attestation_report_submitted(
        org_id, member_id
    )
    await _release(requestor_id, attestation_id)
    account_id = await _org_payout_account(org_id)
    owner = await db_session.get(User, owner_id)

    from app.modules.financials.schemas import PayoutRequest

    with pytest.raises(Exception) as excinfo:
        await financials_service.request_org_payout(
            db_session,
            _FakeRedis(),
            org_id=org_id,
            actor=owner,
            payload=PayoutRequest(
                amount=Decimal("100.00"),
                currency="USD",
                payout_account_id=account_id,
                totp_code=pyotp.TOTP(secret).now(),
            ),
        )
    assert getattr(excinfo.value, "status_code", None) == 403


class _FakeRedis:
    """Async Redis double supporting the TOTP-sensitive verify path."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def incr(self, key: str) -> int:
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.counters)
            self.values.pop(key, None)
            self.counters.pop(key, None)
            self.ttls.pop(key, None)
        return removed


async def test_request_org_payout_creates_org_keyed_payout(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid org payout is created against the org, not any user."""
    fake_task = _FakePayoutTask()
    monkeypatch.setattr(financials_service, "process_payout", fake_task, raising=False)
    org_id, owner_id, secret = await _attestor_org()
    member_id, _ = await _add_member(org_id)
    requestor_id, attestation_id = await _org_attestation_report_submitted(
        org_id, member_id
    )
    await _release(requestor_id, attestation_id)
    account_id = await _org_payout_account(org_id)
    owner = await db_session.get(User, owner_id)

    from app.modules.financials.schemas import PayoutRequest

    result = await financials_service.request_org_payout(
        db_session,
        _FakeRedis(),
        org_id=org_id,
        actor=owner,
        payload=PayoutRequest(
            amount=Decimal("100.00"),
            currency="USD",
            payout_account_id=account_id,
            totp_code=pyotp.TOTP(secret).now(),
        ),
    )

    assert result.net_amount == Decimal("100.00")
    async with async_session_factory() as session:
        payout = await session.scalar(select(Payout))
    assert payout is not None
    assert payout.org_id == org_id
    assert payout.contributor_id is None
    assert fake_task.dispatched == [str(payout.id)]


# --- Invoice identity -----------------------------------------------------


async def test_earnings_statement_bills_org_identity(db_session) -> None:
    """An org attestation's earnings statement bills the org, not the member."""
    org_id, owner_id, _secret = await _attestor_org(legal_name="Attestor Org LLC")
    member_id, _member_user = await _add_member(org_id)
    requestor_id, attestation_id = await _org_attestation_report_submitted(
        org_id, member_id
    )
    await _release(requestor_id, attestation_id)

    attestation = await db_session.get(Attestation, attestation_id)
    buyer_name, buyer_email = await document_service._earnings_buyer_identity(
        db_session, attestation
    )

    owner = await db_session.get(User, owner_id)
    assert buyer_name == "Attestor Org LLC"
    assert buyer_email == owner.email


# --- Endpoints ------------------------------------------------------------


async def test_earnings_endpoint_rbac(client: AsyncClient, clean_state: None) -> None:
    """Earnings endpoint: owner/admin only, unauth 401, plain member 403."""
    del clean_state
    org_id, owner_id, _secret = await _attestor_org()
    _member_id, member_user = await _add_member(org_id)

    unauth = await client.get(f"/v1/orgs/{org_id}/financials/earnings")
    assert unauth.status_code == 401

    forbidden = await client.get(
        f"/v1/orgs/{org_id}/financials/earnings", headers=_auth(member_user)
    )
    assert forbidden.status_code == 403

    allowed = await client.get(
        f"/v1/orgs/{org_id}/financials/earnings", headers=_auth(owner_id)
    )
    assert allowed.status_code == 200
    assert allowed.json()["currency"] == "USD"


async def test_onboard_org_payout_account_endpoint(
    client: AsyncClient, clean_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner onboards an org-owned Stripe payout account."""
    del clean_state

    async def _fake_express(*, email: str, country: str) -> SimpleNamespace:
        return SimpleNamespace(id=f"acct_{uuid4().hex}")

    async def _fake_link(
        *, account_id: str, refresh_url: str, return_url: str
    ) -> SimpleNamespace:
        return SimpleNamespace(url="https://connect.stripe.test/onboard")

    monkeypatch.setattr(
        financials_service.stripe, "create_express_account", _fake_express
    )
    monkeypatch.setattr(financials_service.stripe, "create_account_link", _fake_link)
    org_id, owner_id, _secret = await _attestor_org()

    response = await client.post(
        f"/v1/orgs/{org_id}/financials/payout-accounts",
        headers=_auth(owner_id),
        json={
            "provider": "stripe",
            "refresh_url": "https://app.test/refresh",
            "return_url": "https://app.test/return",
        },
    )

    assert response.status_code == 200
    assert response.json()["onboarding_url"].startswith("https://connect.stripe")
    async with async_session_factory() as session:
        account = await session.scalar(
            select(PayoutAccount).where(PayoutAccount.org_id == org_id)
        )
    assert account is not None
    assert account.user_id is None
    assert account.is_default is True


async def test_onboard_org_payout_account_logs_provider_detail_on_failure(
    client: AsyncClient, clean_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider rejection returns 502 and logs the Stripe detail for triage.

    Regression: the failure log dropped ``error=`` (loguru renders only the
    message), and the provider adapter dropped Stripe's ``error.message``, so a
    502 gave no clue why. Both must survive into the rendered log line.
    """
    from loguru import logger as loguru_logger

    from app.integrations.stripe import StripeProviderError

    detail = "Stripe returned 400. You must enable GB for Express."

    async def _boom_express(*, email: str, country: str) -> SimpleNamespace:
        raise StripeProviderError(detail)

    monkeypatch.setattr(
        financials_service.stripe, "create_express_account", _boom_express
    )
    org_id, owner_id, _secret = await _attestor_org()

    messages: list[str] = []
    sink_id = loguru_logger.add(messages.append, format="{message}")
    try:
        response = await client.post(
            f"/v1/orgs/{org_id}/financials/payout-accounts",
            headers=_auth(owner_id),
            json={
                "provider": "stripe",
                "refresh_url": "https://app.test/refresh",
                "return_url": "https://app.test/return",
            },
        )
    finally:
        loguru_logger.remove(sink_id)

    assert response.status_code == 502
    assert any(detail in message for message in messages)


async def test_org_invoices_endpoint_lists_metadata_only(
    client: AsyncClient, clean_state: None
) -> None:
    """Invoice list returns non-sensitive metadata scoped to the org's work."""
    del clean_state
    org_id, owner_id, _secret = await _attestor_org()
    member_id, _ = await _add_member(org_id)
    _requestor_id, attestation_id = await _org_attestation_report_submitted(
        org_id, member_id
    )
    await _seed_invoice(attestation_id)

    response = await client.get(
        f"/v1/orgs/{org_id}/financials/invoices", headers=_auth(owner_id)
    )

    assert response.status_code == 200
    invoices = response.json()["invoices"]
    assert len(invoices) == 1
    item = invoices[0]
    assert item["source_ref_id"] == str(attestation_id)
    # PII rule: no buyer contact, seller tax id, or account detail in the list.
    assert "buyer_email" not in item
    assert "seller_tax_id" not in item


async def _seed_invoice(attestation_id: UUID) -> None:
    """Insert an issued earnings-statement invoice for an org attestation."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Invoice(
                    series="AUR-ERN",
                    sequence_year=2026,
                    sequence_number=1,
                    invoice_number="AUR-ERN-2026-000001",
                    doc_type="earnings_statement",
                    currency="USD",
                    subtotal=Decimal("500.00"),
                    tax_rate=Decimal("0.0000"),
                    tax_amount=Decimal("0.00"),
                    total=Decimal("500.00"),
                    seller_name="Auracles",
                    seller_tax_id="TAX-123",
                    seller_address="1 Market St",
                    buyer_name="Attestor Org LLC",
                    buyer_email="owner@auracles.space",
                    source_ref_type="attestation",
                    source_ref_id=attestation_id,
                    s3_key=f"invoices/earnings/{attestation_id}.pdf",
                )
            )


async def test_onboard_nigerian_org_payout_account_uses_paystack(
    client: AsyncClient, clean_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Nigerian organization settles on Paystack, not Stripe Connect.

    Connect cannot create a Nigerian payout account at all, so before the
    Paystack rail existed an NG org had no way to be paid — the endpoint
    returned 422 with no alternative.
    """
    del clean_state

    async def _fake_recipient(
        *, name: str, account_number: str, bank_code: str, currency: str
    ) -> SimpleNamespace:
        return SimpleNamespace(
            recipient_code="RCP_org_1", account_name="ATTESTOR ORG LLC"
        )

    monkeypatch.setattr(
        financials_service.paystack, "create_transfer_recipient", _fake_recipient
    )
    org_id, owner_id, _secret = await _attestor_org(country="NG")

    response = await client.post(
        f"/v1/orgs/{org_id}/financials/payout-accounts",
        headers=_auth(owner_id),
        json={
            "provider": "paystack",
            "account_number": "0123456789",
            "bank_code": "044",
        },
    )

    async with async_session_factory() as session:
        account = await session.scalar(
            select(PayoutAccount).where(PayoutAccount.org_id == org_id)
        )

    body = response.json()
    assert response.status_code == 200
    assert body["provider"] == "paystack"
    assert body["onboarding_url"] is None
    assert body["account_name"] == "ATTESTOR ORG LLC"
    assert account is not None
    assert account.user_id is None
    assert account.account_type == "nuban"
    assert account.verified_at is not None


async def test_onboard_org_payout_account_rejects_mismatched_provider(
    client: AsyncClient, clean_state: None
) -> None:
    """An NG org asking for Stripe is refused rather than silently rerouted.

    Registering a Nigerian bank account against Connect would create a payout
    destination that can never be paid.
    """
    del clean_state
    org_id, owner_id, _secret = await _attestor_org(country="NG")

    response = await client.post(
        f"/v1/orgs/{org_id}/financials/payout-accounts",
        headers=_auth(owner_id),
        json={
            "provider": "stripe",
            "refresh_url": "https://app.test/refresh",
            "return_url": "https://app.test/return",
        },
    )

    assert response.status_code == 422


async def test_onboard_org_paystack_payout_account_requires_bank_details(
    client: AsyncClient, clean_state: None
) -> None:
    """Without bank details there is nothing to register, so reject at the schema."""
    del clean_state
    org_id, owner_id, _secret = await _attestor_org(country="NG")

    response = await client.post(
        f"/v1/orgs/{org_id}/financials/payout-accounts",
        headers=_auth(owner_id),
        json={"provider": "paystack"},
    )

    assert response.status_code == 422
