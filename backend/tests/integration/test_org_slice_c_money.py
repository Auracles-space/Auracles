"""Integration tests for Slice C org money: eligibility, history, notifications.

Covers the read-only additions of the organizations end-to-end design §Slice C:
the payout eligibility checklist on org earnings, org payout history, failed
purchase listing, inactive Licenses in the org library, and the post-commit
money notifications (payout requested/completed/failed, purchase
completed/failed, invoice ready, License grants, org Framework suspension).
None of these change how or when money moves; the tests pin that refusals keep
their status codes while the new surfaces explain them.

Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md
§Slice C and Decision 3.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    encrypt_payout_provider_account_id,
    encrypt_totp_secret,
    hash_password,
    hash_payout_provider_account_id,
)
from app.integrations.stripe import StripeProviderError
from app.main import app
from app.modules.admin import service as admin_service
from app.modules.auth.models import User
from app.modules.financials import service as financials_service
from app.modules.financials.ledger import record_financial_event
from app.modules.financials.models import (
    Escrow,
    FinancialEvent,
    Payout,
    PayoutAccount,
    Transaction,
)
from app.modules.financials.schemas import PayoutRequest
from app.modules.frameworks.models import Framework, License, LicenseGrant
from app.modules.invoicing.models import Invoice, InvoiceCounter
from app.modules.organizations import notifications as org_notifications
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgCapability,
    OrgLegalProfile,
    OrgMember,
    OrgMemberNda,
)
from app.modules.webhooks import service as webhook_service
from app.modules.webhooks.models import WebhookEvent
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import financials as financials_tasks
from tests.conftest import open_step_up_window
from tests.integration.test_auth_sessions import FakeRedis

pytestmark = pytest.mark.asyncio

NDA_VERSION = get_settings().org_member_nda_version


class RecordingDispatch:
    """Capture queued org notifications instead of hitting Celery."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def delay(self, **kwargs: Any) -> None:
        """Record one dispatch call."""
        self.sent.append(kwargs)

    def of_type(self, notification_type: str) -> list[dict[str, Any]]:
        """Return the calls for one notification type."""
        return [
            call for call in self.sent if call["notification_type"] == notification_type
        ]


class _NullTask:
    """Swallow Celery dispatches the tests do not assert on."""

    def delay(self, *args: Any, **kwargs: Any) -> None:
        """Ignore the dispatch."""
        del args, kwargs


async def _reset_state() -> None:
    """Delete every row these tests write, in foreign-key-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            for model in (
                WebhookEvent,
                AuditLog,
                FinancialEvent,
                Invoice,
                InvoiceCounter,
                Payout,
                LicenseGrant,
                License,
                Escrow,
                Transaction,
                PayoutAccount,
                Framework,
                OrgLegalProfile,
                OrgAttestorApplication,
                OrgMemberNda,
                OrgCapability,
                OrgMember,
                Organization,
                User,
            ):
                await session.execute(delete(model))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the integration database is at alembic head."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def ctx(
    migrated_database: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[dict[str, Any]]:
    """Reset state, fake Redis and Celery, and record org notifications."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    recorder = RecordingDispatch()
    monkeypatch.setattr(org_notifications, "dispatch_project_notification", recorder)
    monkeypatch.setattr(financials_service, "process_payout", _NullTask())
    monkeypatch.setattr(webhook_service, "generate_invoice_pdf", _NullTask())
    try:
        yield {"redis": fake_redis, "recorder": recorder}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await _reset_state()
        await engine.dispose()


def _auth(user_id: UUID) -> dict[str, str]:
    """Build bearer headers for one user."""
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id, roles=[])}"}


async def _user(prefix: str) -> UUID:
    """Create a verified, 2FA-enrolled user and return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
                kyc_status="verified",
                totp_enabled=True,
                totp_secret=encrypt_totp_secret("JBSWY3DPEHPK3PXP"),
            )
            session.add(user)
            await session.flush()
            return user.id


async def _org(
    *,
    name: str = "Acme",
    attestor_approved: bool = True,
    kyb_status: str = "verified",
    contributor_active: bool = False,
    tax_document: bool = False,
) -> tuple[UUID, UUID]:
    """Seed a verified org with one owner. Return (org_id, owner_user_id)."""
    owner_id = await _user("owner")
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"org-{uuid4().hex[:8]}",
                name=name,
                country="US",
                created_by=owner_id,
            )
            session.add(org)
            await session.flush()
            member = OrgMember(org_id=org.id, user_id=owner_id, role="owner")
            session.add(member)
            await session.flush()
            session.add(OrgMemberNda(member_id=member.id, nda_version=NDA_VERSION))
            session.add(
                OrgLegalProfile(
                    org_id=org.id,
                    legal_name=f"{name} Ltd",
                    registration_number="RC000001",
                    kyb_status=kyb_status,
                    kyb_verified_at=now if kyb_status == "verified" else None,
                    tax_document_type="w9" if tax_document else None,
                    tax_document_key=(
                        "org-legal-profiles/tax.pdf" if tax_document else None
                    ),
                )
            )
            session.add(
                OrgCapability(org_id=org.id, capability="operator", status="active")
            )
            if attestor_approved:
                session.add(
                    OrgCapability(org_id=org.id, capability="attestor", status="active")
                )
                session.add(
                    OrgAttestorApplication(
                        org_id=org.id,
                        status="approved",
                        specializations=["tax"],
                        jurisdictions=["US"],
                        sectors=["tax"],
                        credentials_summary="Chartered reviewers.",
                        sample_work={},
                        professional_references="On request.",
                    )
                )
            if contributor_active:
                session.add(
                    OrgCapability(
                        org_id=org.id, capability="contributor", status="active"
                    )
                )
            return org.id, owner_id


async def _member(org_id: UUID, *, role: str = "member") -> tuple[UUID, UUID]:
    """Add a member. Return (member_id, user_id)."""
    user_id = await _user(role)
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=org_id, user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            session.add(OrgMemberNda(member_id=member.id, nda_version=NDA_VERSION))
            return member.id, user_id


async def _payout_account(
    org_id: UUID, *, verified: bool = True, provider: str = "stripe"
) -> tuple[UUID, str]:
    """Create an org payout account. Return (id, plaintext provider account id)."""
    provider_account_id = f"acct_{uuid4().hex}"
    async with async_session_factory() as session:
        async with session.begin():
            account = PayoutAccount(
                org_id=org_id,
                provider=provider,
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
            return account.id, provider_account_id


async def _balance(org_id: UUID, amount: Decimal = Decimal("1000.00")) -> None:
    """Seed a cleared org marketplace sale so the org has an available balance."""
    buyer_id = await _user("buyer")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Transaction(
                    payer_id=buyer_id,
                    payee_org_id=org_id,
                    amount=amount,
                    currency="USD",
                    platform_commission=Decimal("0.00"),
                    net_amount=amount,
                    transaction_type="purchase",
                    status="completed",
                    provider="stripe",
                    provider_ref=f"pi_{uuid4().hex}",
                    ref_id=uuid4(),
                    ref_type="framework",
                    created_at=datetime.now(UTC) - timedelta(days=60),
                )
            )


async def _payout(
    org_id: UUID,
    account_id: UUID,
    *,
    status: str = "processing",
    net: Decimal = Decimal("100.00"),
    provider_ref: str | None = None,
    requester_id: UUID | None = None,
    initiated_at: datetime | None = None,
) -> UUID:
    """Seed an org payout row, auditing the requester when given."""
    async with async_session_factory() as session:
        async with session.begin():
            payout = Payout(
                org_id=org_id,
                payout_account_id=account_id,
                amount=net,
                currency="USD",
                commission_deducted=Decimal("0.00"),
                net_amount=net,
                status=status,
                provider_ref=provider_ref,
                initiated_at=initiated_at or datetime.now(UTC),
            )
            session.add(payout)
            await session.flush()
            if requester_id is not None:
                session.add(
                    AuditLog(
                        actor_id=requester_id,
                        action="payout_requested",
                        target_type="payout",
                        target_id=payout.id,
                        metadata_={"org_id": str(org_id)},
                    )
                )
            return payout.id


async def _framework(title: str = "Revenue Playbook", **kwargs: Any) -> UUID:
    """Seed a published Framework."""
    contributor_id = kwargs.pop("contributor_id", None)
    if contributor_id is None and kwargs.get("contributor_org_id") is None:
        contributor_id = await _user("seller")
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title=title,
                description="Practical operating system.",
                status="published",
                category="operations",
                price=Decimal("249.00"),
                currency="USD",
                license_types=["single_user", "team"],
                published_at=datetime.now(UTC),
                **kwargs,
            )
            session.add(framework)
            await session.flush()
            return framework.id


async def _org_license(
    org_id: UUID, framework_id: UUID, *, status: str = "active"
) -> UUID:
    """Seed an org-owned License."""
    async with async_session_factory() as session:
        async with session.begin():
            license_row = License(
                framework_id=framework_id,
                licensee_org_id=org_id,
                license_type="team",
                status=status,
                version_at_grant="1.0.0",
                seats_used=1,
                seats_total=10,
            )
            session.add(license_row)
            await session.flush()
            return license_row.id


async def _eligibility(org_id: UUID) -> dict[str, Any]:
    """Return the org earnings payout_eligibility as plain data."""
    async with async_session_factory() as session:
        earnings = await financials_service.get_org_earnings(session, org_id=org_id)
    return earnings.payout_eligibility.model_dump()


def _codes(eligibility: dict[str, Any]) -> list[str]:
    """Return reason codes from an eligibility payload."""
    return [reason["code"] for reason in eligibility["reasons"]]


# --- 1. Payout eligibility --------------------------------------------------


async def test_eligible_org_has_no_reasons(ctx: dict[str, Any]) -> None:
    """A verified, funded org with a verified account is eligible with no reasons."""
    org_id, _owner = await _org()
    await _payout_account(org_id)
    await _balance(org_id)

    eligibility = await _eligibility(org_id)

    assert eligibility == {"eligible": True, "reasons": []}


async def test_kyb_and_account_reasons_carry_action_paths(ctx: dict[str, Any]) -> None:
    """Unverified KYB and a missing verified account each name where to fix them."""
    org_id, _owner = await _org(kyb_status="pending")
    await _payout_account(org_id, verified=False)
    await _balance(org_id)

    eligibility = await _eligibility(org_id)
    reasons = {reason["code"]: reason for reason in eligibility["reasons"]}

    assert eligibility["eligible"] is False
    assert reasons["kyb_not_verified"]["action_path"] == (
        f"/dashboard/organizations/{org_id}/verification"
    )
    assert reasons["no_verified_payout_account"]["action_path"] == (
        f"/dashboard/organizations/{org_id}/financials"
    )


async def test_tax_document_reason_applies_only_on_contributor_path(
    ctx: dict[str, Any],
) -> None:
    """A contributor org without an attestor approval needs its tax document."""
    org_id, _owner = await _org(attestor_approved=False, contributor_active=True)
    await _payout_account(org_id)
    await _balance(org_id)
    attestor_org, _ = await _org(name="Attest", attestor_approved=True)
    await _payout_account(attestor_org)
    await _balance(attestor_org)

    contributor_eligibility = await _eligibility(org_id)
    attestor_eligibility = await _eligibility(attestor_org)

    reasons = {r["code"]: r for r in contributor_eligibility["reasons"]}
    assert "tax_document_missing" in reasons
    assert reasons["tax_document_missing"]["action_path"] == (
        f"/dashboard/organizations/{org_id}/verification"
    )
    assert "tax_document_missing" not in _codes(attestor_eligibility)


async def test_org_without_any_payout_capability_is_told_so(
    ctx: dict[str, Any],
) -> None:
    """No approved attestor application and no contributor capability blocks payout."""
    org_id, _owner = await _org(attestor_approved=False)
    await _payout_account(org_id)
    await _balance(org_id)

    assert "no_payout_capability" in _codes(await _eligibility(org_id))


async def test_below_minimum_names_the_formatted_minimum(ctx: dict[str, Any]) -> None:
    """An org with no cleared balance sees the minimum in its own currency."""
    org_id, _owner = await _org()
    await _payout_account(org_id)

    eligibility = await _eligibility(org_id)
    reason = next(
        r for r in eligibility["reasons"] if r["code"] == "below_minimum_payout"
    )
    async with async_session_factory() as session:
        minimum = await financials_service._minimum_payout(session, "USD")

    assert org_notifications.format_money(minimum, "USD") in reason["message"]
    assert reason["action_path"] is None


async def test_suspended_and_in_flight_reasons(ctx: dict[str, Any]) -> None:
    """Suspension and an in-flight payout are reported without an action."""
    org_id, _owner = await _org()
    account_id, _ = await _payout_account(org_id)
    await _balance(org_id)
    await _payout(org_id, account_id, status="pending")
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Organization)
                .where(Organization.id == org_id)
                .values(suspended_at=datetime.now(UTC), suspension_reason="Review")
            )

    eligibility = await _eligibility(org_id)
    reasons = {r["code"]: r for r in eligibility["reasons"]}

    assert reasons["org_suspended"]["action_path"] is None
    assert reasons["payout_in_progress"]["action_path"] is None


async def test_earnings_endpoint_exposes_eligibility(
    client: AsyncClient, ctx: dict[str, Any]
) -> None:
    """The org earnings route returns the checklist rather than a 403."""
    org_id, owner_id = await _org()

    response = await client.get(
        f"/v1/orgs/{org_id}/financials/earnings", headers=_auth(owner_id)
    )

    assert response.status_code == 200
    body = response.json()["payout_eligibility"]
    assert body["eligible"] is False
    assert "no_verified_payout_account" in _codes(body)


async def test_request_org_payout_refusals_keep_status_codes(
    ctx: dict[str, Any],
) -> None:
    """The shared checks still refuse with 409 (in flight) and 403 (ineligible)."""
    org_id, owner_id = await _org()
    account_id, _ = await _payout_account(org_id)
    await _balance(org_id)
    await _payout(org_id, account_id, status="pending")
    ineligible_org, ineligible_owner = await _org(name="NoCap", attestor_approved=False)
    ineligible_account, _ = await _payout_account(ineligible_org)
    await _balance(ineligible_org)

    async def _request(org: UUID, actor_id: UUID, account: UUID) -> int:
        async with async_session_factory() as session:
            actor = await session.get(User, actor_id)
            with pytest.raises(Exception) as excinfo:
                await financials_service.request_org_payout(
                    session,
                    org_id=org,
                    actor=actor,
                    payload=PayoutRequest(
                        amount=Decimal("100.00"),
                        currency="USD",
                        payout_account_id=account,
                    ),
                )
        return getattr(excinfo.value, "status_code", 0)

    assert await _request(org_id, owner_id, account_id) == 409
    assert await _request(ineligible_org, ineligible_owner, ineligible_account) == 403


# --- 2. Payout history ------------------------------------------------------


async def test_payout_history_rbac_and_scoping(
    client: AsyncClient, ctx: dict[str, Any]
) -> None:
    """401 unauthenticated, 403 member, owner sees only its org, newest first."""
    org_id, owner_id = await _org()
    _member_id, member_user = await _member(org_id)
    account_id, _ = await _payout_account(org_id)
    older = await _payout(
        org_id,
        account_id,
        status="completed",
        initiated_at=datetime.now(UTC) - timedelta(days=3),
    )
    newer = await _payout(org_id, account_id, status="failed")
    async with async_session_factory() as session:
        async with session.begin():
            await record_financial_event(
                session,
                entity_type="payout",
                entity_id=newer,
                event_type="payout_failed",
                from_status="processing",
                to_status="failed",
                amount=Decimal("100.00"),
                currency="USD",
                provider="stripe",
                reason_code="account_closed",
                reason_message="The destination account is closed.",
            )
    other_org, _ = await _org(name="Other")
    other_account, _ = await _payout_account(other_org)
    await _payout(other_org, other_account)
    path = f"/v1/orgs/{org_id}/financials/payouts"

    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=_auth(member_user))).status_code == 403
    response = await client.get(path, headers=_auth(owner_id))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert [row["id"] for row in body["payouts"]] == [str(newer), str(older)]
    assert body["payouts"][0]["failure_reason"] == "The destination account is closed."
    assert body["payouts"][0]["provider"] == "stripe"
    assert body["payouts"][1]["failure_reason"] is None


# --- 3. Notifications -------------------------------------------------------


async def test_payout_request_notifies_owners_end_to_end(
    client: AsyncClient, ctx: dict[str, Any]
) -> None:
    """A successful org payout request queues org_payout_requested to owners."""
    org_id, owner_id = await _org()
    account_id, _ = await _payout_account(org_id)
    await _balance(org_id)
    await open_step_up_window(ctx["redis"], owner_id)

    response = await client.post(
        f"/v1/orgs/{org_id}/financials/payouts",
        headers=_auth(owner_id),
        json={
            "amount": "100.00",
            "currency": "USD",
            "payout_account_id": str(account_id),
        },
    )

    assert response.status_code == 200
    calls = ctx["recorder"].of_type("org_payout_requested")
    assert [call["user_id"] for call in calls] == [str(owner_id)]
    assert "$100.00" in calls[0]["body"]
    assert calls[0]["link"] == f"/dashboard/organizations/{org_id}/financials"


async def test_paystack_transfer_outcomes_notify_owners_and_requester(
    ctx: dict[str, Any],
) -> None:
    """Paystack transfer success/failure flips reach owners plus the requester."""
    org_id, owner_id = await _org()
    _admin_member, admin_user = await _member(org_id, role="admin")
    account_id, _ = await _payout_account(org_id, provider="paystack")
    paid = await _payout(
        org_id, account_id, provider_ref="payout-paid", requester_id=admin_user
    )
    failed = await _payout(
        org_id, account_id, provider_ref="payout-failed", requester_id=admin_user
    )

    async def _apply(ref: str, status: str, extra: dict[str, Any]) -> None:
        envelope = {"data": {"object": {"id": ref, **extra}}}
        async with async_session_factory() as session:
            async with session.begin():
                work = await webhook_service._handle_transfer_event(
                    session, envelope, payout_status=status, provider="paystack"
                )
        for callback in work:
            callback()

    await _apply("payout-paid", "completed", {})
    await _apply("payout-failed", "failed", {"gateway_response": "Account closed"})

    completed = ctx["recorder"].of_type("org_payout_completed")
    failed_calls = ctx["recorder"].of_type("org_payout_failed")
    assert [c["user_id"] for c in completed] == [str(owner_id), str(admin_user)]
    assert completed[0]["dedupe_key"].endswith(str(paid))
    assert [c["user_id"] for c in failed_calls] == [str(owner_id), str(admin_user)]
    assert failed_calls[0]["dedupe_key"].endswith(str(failed))


async def test_stripe_bank_payout_paid_notifies_org_owners(
    ctx: dict[str, Any],
) -> None:
    """Stripe payout.paid settling an org payout notifies its owners."""
    org_id, owner_id = await _org()
    account_id, provider_account_id = await _payout_account(org_id)
    await _payout(
        org_id,
        account_id,
        provider_ref="tr_org",
        initiated_at=datetime.now(UTC) - timedelta(hours=1),
    )
    event = {
        "id": "evt_org_payout_paid",
        "type": "payout.paid",
        "account": provider_account_id,
        "data": {
            "object": {"id": "po_org", "created": int(datetime.now(UTC).timestamp())}
        },
    }

    async with async_session_factory() as session:
        async with session.begin():
            work = await webhook_service._handle_connected_payout_paid(session, event)
    for callback in work:
        callback()

    calls = ctx["recorder"].of_type("org_payout_completed")
    assert [c["user_id"] for c in calls] == [str(owner_id)]


async def test_org_purchase_webhook_notifies_owners_and_initiator(
    client: AsyncClient,
    ctx: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stripe settlement of an admin-started org purchase notifies owner and admin."""
    org_id, owner_id = await _org()
    _admin_member, admin_user = await _member(org_id, role="admin")
    framework_id = await _framework()
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Organization)
                .where(Organization.id == org_id)
                .values(stripe_customer_id="cus_slice_c")
            )
    await open_step_up_window(ctx["redis"], admin_user)

    class _Intent:
        id = "pi_slice_c"
        client_secret = "secret"

    async def _fake_intent(**kwargs: Any) -> _Intent:
        del kwargs
        return _Intent()

    monkeypatch.setattr(
        financials_service.stripe, "create_payment_intent", _fake_intent
    )
    purchase = await client.post(
        f"/v1/orgs/{org_id}/frameworks/{framework_id}/purchase",
        headers=_auth(admin_user),
        json={"license_type": "team"},
    )
    assert purchase.status_code == 200, purchase.text
    transaction_id = purchase.json()["transaction_id"]

    event = {
        "id": "evt_slice_c_purchase",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_slice_c",
                "metadata": {
                    "transaction_id": transaction_id,
                    "kind": "purchase",
                    "framework_id": str(framework_id),
                    "license_type": "team",
                    "payer_org_id": str(org_id),
                },
            }
        },
    }
    monkeypatch.setattr(
        webhook_service.stripe, "verify_webhook", lambda payload, header: event
    )
    webhook = await client.post(
        "/v1/webhooks/stripe", content=b"{}", headers={"Stripe-Signature": "sig"}
    )

    assert webhook.status_code == 200
    calls = ctx["recorder"].of_type("org_purchase_completed")
    assert [c["user_id"] for c in calls] == [str(owner_id), str(admin_user)]
    assert "Revenue Playbook" in calls[0]["title"]
    assert calls[0]["link"] == f"/dashboard/organizations/{org_id}/operator/library"


async def test_org_purchase_provider_failure_notifies_with_billing_link(
    client: AsyncClient,
    ctx: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A checkout the provider refuses to start tells owners it failed."""
    org_id, owner_id = await _org()
    framework_id = await _framework()
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Organization)
                .where(Organization.id == org_id)
                .values(stripe_customer_id="cus_slice_c_fail")
            )
    await open_step_up_window(ctx["redis"], owner_id)

    async def _boom(**kwargs: Any) -> None:
        del kwargs
        raise StripeProviderError("card network down")

    monkeypatch.setattr(financials_service.stripe, "create_payment_intent", _boom)
    response = await client.post(
        f"/v1/orgs/{org_id}/frameworks/{framework_id}/purchase",
        headers=_auth(owner_id),
        json={"license_type": "team"},
    )

    assert response.status_code == 502
    calls = ctx["recorder"].of_type("org_purchase_failed")
    assert [c["user_id"] for c in calls] == [str(owner_id)]
    assert calls[0]["link"] == f"/dashboard/organizations/{org_id}/financials"


async def test_org_purchase_webhook_failure_notifies_with_reason(
    ctx: dict[str, Any],
) -> None:
    """A provider-declined org charge notifies owners with the decline reason."""
    org_id, owner_id = await _org()
    framework_id = await _framework()
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_org_id=org_id,
                amount=Decimal("249.00"),
                currency="USD",
                net_amount=Decimal("249.00"),
                transaction_type="purchase",
                status="pending",
                provider="stripe",
                provider_ref="pi_declined",
                ref_id=framework_id,
                ref_type="framework",
            )
            session.add(transaction)
            await session.flush()
            transaction_id = transaction.id
    event = {
        "type": "payment_intent.payment_failed",
        "data": {
            "object": {
                "id": "pi_declined",
                "metadata": {"transaction_id": str(transaction_id), "kind": "purchase"},
                "last_payment_error": {
                    "code": "card_declined",
                    "decline_code": "insufficient_funds",
                    "message": "Your card has insufficient funds.",
                },
            }
        },
    }

    async with async_session_factory() as session:
        async with session.begin():
            work = await webhook_service._handle_purchase_failed(session, event)
    for callback in work:
        callback()

    calls = ctx["recorder"].of_type("org_purchase_failed")
    assert [c["user_id"] for c in calls] == [str(owner_id)]
    assert "Reason:" in calls[0]["body"]


async def test_invoice_pdf_generation_notifies_org_owners(ctx: dict[str, Any]) -> None:
    """Rendering an org purchase invoice tells owners it is ready."""
    org_id, owner_id = await _org()
    framework_id = await _framework()
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_org_id=org_id,
                amount=Decimal("249.00"),
                currency="USD",
                net_amount=Decimal("249.00"),
                transaction_type="purchase",
                status="completed",
                provider="stripe",
                provider_ref="pi_invoice",
                ref_id=framework_id,
                ref_type="framework",
            )
            session.add(transaction)
            await session.flush()
            transaction_id = transaction.id

    await financials_tasks._notify_org_invoice_ready(str(transaction_id))

    calls = ctx["recorder"].of_type("org_invoice_ready")
    assert [c["user_id"] for c in calls] == [str(owner_id)]
    assert "Revenue Playbook" in calls[0]["body"]


async def test_individual_invoice_generation_sends_no_org_notice(
    ctx: dict[str, Any],
) -> None:
    """An individual buyer's invoice never produces an org notification."""
    buyer = await _user("buyer")
    framework_id = await _framework()
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_id=buyer,
                amount=Decimal("249.00"),
                currency="USD",
                net_amount=Decimal("249.00"),
                transaction_type="purchase",
                status="completed",
                provider="stripe",
                ref_id=framework_id,
                ref_type="framework",
            )
            session.add(transaction)
            await session.flush()
            transaction_id = transaction.id

    await financials_tasks._notify_org_invoice_ready(str(transaction_id))

    assert ctx["recorder"].of_type("org_invoice_ready") == []


async def test_license_grant_and_revoke_notify_the_grantee_only(
    client: AsyncClient, ctx: dict[str, Any]
) -> None:
    """Grantee hears grant and revoke; the owner granting to themself does not."""
    org_id, owner_id = await _org()
    member_id, member_user = await _member(org_id)
    framework_id = await _framework()
    license_id = await _org_license(org_id, framework_id)
    async with async_session_factory() as session:
        owner_member_id = await session.scalar(
            select(OrgMember.id).where(OrgMember.user_id == owner_id)
        )

    granted = await client.post(
        f"/v1/orgs/{org_id}/licenses/{license_id}/grants",
        headers=_auth(owner_id),
        json={"member_id": str(member_id)},
    )
    self_grant = await client.post(
        f"/v1/orgs/{org_id}/licenses/{license_id}/grants",
        headers=_auth(owner_id),
        json={"member_id": str(owner_member_id)},
    )
    revoked = await client.delete(
        f"/v1/orgs/{org_id}/licenses/{license_id}/grants/{granted.json()['id']}",
        headers=_auth(owner_id),
    )

    assert granted.status_code == 201
    assert self_grant.status_code == 201
    assert revoked.status_code == 204
    grants = ctx["recorder"].of_type("org_license_granted")
    revokes = ctx["recorder"].of_type("org_license_revoked")
    assert [c["user_id"] for c in grants] == [str(member_user)]
    assert [c["user_id"] for c in revokes] == [str(member_user)]
    assert grants[0]["link"] == f"/dashboard/organizations/{org_id}/operator/library"


async def test_member_removal_sends_one_notice_not_one_per_grant(
    client: AsyncClient, ctx: dict[str, Any]
) -> None:
    """Removing a member who held grants sends a single removal notice.

    The removal notice already says shared library access ended; per-grant
    "access ended" notices repeated it and linked to a library the former
    member can no longer open.
    """
    org_id, owner_id = await _org()
    member_id, member_user = await _member(org_id)
    license_id = await _org_license(org_id, await _framework())
    async with async_session_factory() as session:
        async with session.begin():
            session.add(LicenseGrant(license_id=license_id, member_id=member_id))

    response = await client.delete(
        f"/v1/orgs/{org_id}/members/{member_id}", headers=_auth(owner_id)
    )

    assert response.status_code in {200, 204}
    assert ctx["recorder"].of_type("org_license_revoked") == []
    removed = ctx["recorder"].of_type("org_member_removed")
    assert [c["user_id"] for c in removed] == [str(member_user)]
    assert "shared library access" in str(removed[0]["body"])


async def test_admin_suspending_org_framework_notifies_owners(
    ctx: dict[str, Any],
) -> None:
    """An admin takedown of an org Framework reaches its owners with the reason."""
    org_id, owner_id = await _org()
    framework_id = await _framework(contributor_org_id=org_id)
    admin_id = await _user("admin")

    async with async_session_factory() as session:
        admin = await session.get(User, admin_id)
        await admin_service.suspend_framework(
            session, admin, framework_id, "Copyright complaint upheld."
        )

    calls = ctx["recorder"].of_type("org_framework_suspended")
    assert [c["user_id"] for c in calls] == [str(owner_id)]
    assert "Copyright complaint upheld." in calls[0]["body"]


# --- 4. Library inactive Licenses -------------------------------------------


async def test_library_include_inactive_lists_revoked_and_expired(
    client: AsyncClient, ctx: dict[str, Any]
) -> None:
    """Default stays active-only; include_inactive adds expired and revoked."""
    org_id, owner_id = await _org()
    active = await _org_license(org_id, await _framework("Active"))
    expired = await _org_license(org_id, await _framework("Expired"), status="expired")
    revoked = await _org_license(org_id, await _framework("Revoked"), status="revoked")

    default = await client.get(f"/v1/orgs/{org_id}/library", headers=_auth(owner_id))
    inclusive = await client.get(
        f"/v1/orgs/{org_id}/library?include_inactive=true", headers=_auth(owner_id)
    )

    assert default.status_code == 200
    assert [item["license_id"] for item in default.json()["items"]] == [str(active)]
    statuses = {
        item["license_id"]: item["status"] for item in inclusive.json()["items"]
    }
    assert statuses == {
        str(active): "active",
        str(expired): "expired",
        str(revoked): "revoked",
    }


async def test_revoked_license_download_still_refused(
    client: AsyncClient, ctx: dict[str, Any]
) -> None:
    """Listing an inactive License never unlocks its Artifacts."""
    org_id, owner_id = await _org()
    revoked = await _org_license(org_id, await _framework(), status="revoked")

    response = await client.post(
        f"/v1/orgs/{org_id}/library/{revoked}/artifacts/{uuid4()}/download",
        headers=_auth(owner_id),
    )

    assert response.status_code == 403


# --- 5. Failed purchases ----------------------------------------------------


async def test_failed_purchases_listing(
    client: AsyncClient, ctx: dict[str, Any]
) -> None:
    """Owners see their org's failed purchases with reasons, newest first."""
    org_id, owner_id = await _org()
    _member_id, member_user = await _member(org_id)
    framework_id = await _framework()
    other_org, _ = await _org(name="Other")
    now = datetime.now(UTC)

    async def _purchase(org: UUID, status: str, created_at: datetime) -> UUID:
        async with async_session_factory() as session:
            async with session.begin():
                row = Transaction(
                    payer_org_id=org,
                    amount=Decimal("249.00"),
                    currency="USD",
                    net_amount=Decimal("249.00"),
                    transaction_type="purchase",
                    status=status,
                    provider="paystack",
                    ref_id=framework_id,
                    ref_type="framework",
                    created_at=created_at,
                )
                session.add(row)
                await session.flush()
                return row.id

    older = await _purchase(org_id, "failed", now - timedelta(days=2))
    newer = await _purchase(org_id, "failed", now)
    await _purchase(org_id, "completed", now)
    await _purchase(other_org, "failed", now)
    async with async_session_factory() as session:
        async with session.begin():
            await record_financial_event(
                session,
                entity_type="transaction",
                entity_id=newer,
                event_type="purchase_failed",
                from_status="pending",
                to_status="failed",
                amount=Decimal("249.00"),
                currency="USD",
                provider="paystack",
                reason_code="insufficient_funds",
                reason_message="Insufficient funds.",
            )
    path = f"/v1/orgs/{org_id}/financials/purchases?status=failed"

    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=_auth(member_user))).status_code == 403
    response = await client.get(path, headers=_auth(owner_id))

    assert response.status_code == 200
    purchases = response.json()["purchases"]
    assert [p["transaction_id"] for p in purchases] == [str(newer), str(older)]
    assert purchases[0]["failure_reason"] == "Insufficient funds."
    assert purchases[0]["framework_title"] == "Revenue Playbook"
    assert purchases[1]["failure_reason"] is None
