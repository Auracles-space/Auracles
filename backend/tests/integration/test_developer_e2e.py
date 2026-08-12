"""End-to-end integration tests for Phase 5a Developer platform workflows."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select, update

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
from app.integrations import stripe
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.developer import commission_service
from app.modules.developer.models import (
    ApiKey,
    ApiRequestLog,
    DeveloperAccount,
    DeveloperApplication,
    PartnerCommission,
    PartnerPayout,
    PartnerPurchaseAttribution,
    PartnerWebhook,
    PartnerWebhookDelivery,
)
from app.modules.financials.models import FinancialEvent, PayoutAccount, Transaction
from app.modules.frameworks.models import Framework, License, Review
from app.modules.frameworks.models_artifact import (
    Artifact,
    ArtifactDownload,
    ArtifactPiiAudit,
    ArtifactRarityAudit,
)
from app.modules.notifications.models import Notification
from app.modules.webhooks import service as stripe_webhook_service
from app.modules.webhooks.models import WebhookEvent
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import developer_beat, partner_webhooks


class FakeRedis:
    """Redis test double for auth TOTP and Partner API rate limiting."""

    def __init__(self) -> None:
        """Create empty fake Redis storage."""
        self.values: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored value, counter, or None."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        """Set a key, respecting Redis NX semantics needed by throttles."""
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def incr(self, key: str) -> int:
        """Increment and return a fake Redis counter."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        """Record an expiry request."""
        self.ttls[key] = seconds
        return True

    async def delete(self, *keys: str) -> int:
        """Delete string, counter, and sorted-set keys."""
        removed = 0
        for key in keys:
            removed += int(
                key in self.values or key in self.counters or key in self.sorted_sets
            )
            self.values.pop(key, None)
            self.counters.pop(key, None)
            self.sorted_sets.pop(key, None)
            self.ttls.pop(key, None)
        return removed

    async def eval(
        self,
        _script: str,
        _numkeys: int,
        key: str,
        now_ms: int,
        window_ms: int,
        limit: int,
        member_suffix: str | None = None,
    ) -> list[int]:
        """Emulate the sliding-window Lua script used by Partner API auth."""
        del member_suffix
        bucket = self.sorted_sets.setdefault(key, {})
        cutoff = now_ms - window_ms
        for member, score in list(bucket.items()):
            if score < cutoff:
                bucket.pop(member, None)
        if len(bucket) >= limit:
            return [0, len(bucket)]
        bucket[f"{now_ms}:{len(bucket)}"] = float(now_ms)
        return [1, len(bucket)]


class FakeStripeCustomer:
    """Small fake object matching the Stripe customer adapter return shape."""

    def __init__(self, customer_id: str) -> None:
        """Store the fake Stripe customer id."""
        self.id = customer_id


class FakeStripePaymentIntent:
    """Small fake object matching the Stripe PaymentIntent adapter return shape."""

    def __init__(self, payment_intent_id: str, client_secret: str) -> None:
        """Store fake Stripe PaymentIntent fields."""
        self.id = payment_intent_id
        self.client_secret = client_secret


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure all Phase 5a tables exist for the E2E workflow."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


async def cleanup_developer_e2e_state() -> None:
    """Delete E2E rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(update(Framework).values(preview_artifact_id=None))
        await session.execute(delete(WebhookEvent))
        await session.execute(delete(AuditLog))
        await session.execute(delete(PartnerWebhookDelivery))
        await session.execute(delete(PartnerWebhook))
        await session.execute(delete(PartnerCommission))
        await session.execute(delete(PartnerPayout))
        await session.execute(delete(PartnerPurchaseAttribution))
        await session.execute(delete(ApiRequestLog))
        await session.execute(delete(Notification))
        await session.execute(delete(PayoutAccount))
        await session.execute(delete(License))
        await session.execute(delete(Review))
        await session.execute(delete(ArtifactDownload))
        await session.execute(delete(ArtifactRarityAudit))
        await session.execute(delete(ArtifactPiiAudit))
        await session.execute(delete(Artifact))
        await session.execute(delete(ApiKey))
        await session.execute(delete(DeveloperAccount))
        await session.execute(delete(DeveloperApplication))
        # Written by the purchase and payout paths this flow exercises, and
        # keyed to both the actor and the transaction, so it has to go before
        # either of those.
        await session.execute(delete(FinancialEvent))
        await session.execute(delete(Transaction))
        await session.execute(delete(Framework))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture
async def developer_e2e_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset state and replace external services with deterministic fakes."""
    fake_redis = FakeRedis()
    webhook_verified_events: list[dict[str, Any]] = []
    dispatched_webhooks: list[str] = []
    dispatched_payouts: list[str] = []
    invoice_jobs: list[str] = []
    await engine.dispose()
    await cleanup_developer_e2e_state()

    async def fake_create_customer(
        *,
        email: str,
        name: str,
        idempotency_key: str,
    ) -> FakeStripeCustomer:
        """Return a deterministic Stripe customer without network access."""
        del name, idempotency_key
        customer_hash = hashlib.sha1(email.encode()).hexdigest()[:10]
        return FakeStripeCustomer(f"cus_{customer_hash}")

    async def fake_create_payment_intent(
        *,
        customer_id: str,
        amount: Decimal,
        currency: str,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> FakeStripePaymentIntent:
        """Return a deterministic PaymentIntent using the transaction metadata."""
        del customer_id, amount, currency, idempotency_key
        return FakeStripePaymentIntent(
            payment_intent_id="pi_developer_e2e",
            client_secret=f"secret_{metadata['transaction_id']}",
        )

    def fake_verify_webhook(
        payload: bytes,
        signature_header: str | None,
    ) -> dict[str, Any]:
        """Return the currently configured Stripe event for webhook ingestion."""
        del payload
        if signature_header != "valid-signature":
            raise stripe_webhook_service.stripe.StripeProviderError("bad signature")
        return webhook_verified_events[-1]

    def fake_invoice_delay(transaction_id: str) -> None:
        """Record invoice generation dispatches."""
        invoice_jobs.append(transaction_id)

    def fake_webhook_delay(delivery_id: str) -> None:
        """Record Partner webhook delivery dispatches."""
        dispatched_webhooks.append(delivery_id)

    def fake_payout_delay(payout_id: str) -> None:
        """Record Partner payout processing dispatches."""
        dispatched_payouts.append(payout_id)

    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr(stripe, "create_customer", fake_create_customer)
    monkeypatch.setattr(stripe, "create_payment_intent", fake_create_payment_intent)
    monkeypatch.setattr(
        stripe_webhook_service.stripe,
        "verify_webhook",
        fake_verify_webhook,
    )
    monkeypatch.setattr(
        stripe_webhook_service.generate_invoice_pdf,
        "delay",
        fake_invoice_delay,
    )
    monkeypatch.setattr(
        partner_webhooks.deliver_partner_webhook,
        "delay",
        fake_webhook_delay,
    )
    monkeypatch.setattr(
        commission_service.process_partner_payout,
        "delay",
        fake_payout_delay,
    )
    try:
        yield {
            "dispatched_payouts": dispatched_payouts,
            "dispatched_webhooks": dispatched_webhooks,
            "invoice_jobs": invoice_jobs,
            "stripe_events": webhook_verified_events,
        }
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup_developer_e2e_state()
        await engine.dispose()


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for an E2E actor."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def create_e2e_users() -> dict[str, Any]:
    """Create Developer applicant, admin, contributor, and operator users."""
    admin_totp_secret = pyotp.random_base32()
    developer_totp_secret = pyotp.random_base32()
    async with async_session_factory() as session:
        async with session.begin():
            admin = User(
                email="developer-e2e-admin@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Developer E2E Admin",
                email_verified=True,
                totp_enabled=True,
                totp_secret=encrypt_totp_secret(admin_totp_secret),
            )
            developer = User(
                email="developer-e2e-partner@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Developer E2E Partner",
                email_verified=True,
                kyc_status="verified",
                totp_enabled=True,
                totp_secret=encrypt_totp_secret(developer_totp_secret),
            )
            contributor = User(
                email="developer-e2e-contributor@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Developer E2E Contributor",
                email_verified=True,
                kyc_status="verified",
            )
            operator = User(
                email="developer-e2e-operator@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Developer E2E Operator",
                email_verified=True,
            )
            session.add_all([admin, developer, contributor, operator])
            await session.flush()
            session.add_all(
                [
                    UserRole(
                        user_id=admin.id,
                        role="admin",
                        approved_at=datetime.now(UTC),
                    ),
                    UserRole(
                        user_id=contributor.id,
                        role="contributor",
                        approved_at=datetime.now(UTC),
                    ),
                    UserRole(
                        user_id=operator.id,
                        role="operator",
                        approved_at=datetime.now(UTC),
                    ),
                ]
            )
            payout_account = PayoutAccount(
                user_id=developer.id,
                provider="stripe",
                provider_account_id=encrypt_payout_provider_account_id(
                    "acct_developer_e2e"
                ),
                provider_account_lookup_hash=hash_payout_provider_account_id(
                    "acct_developer_e2e"
                ),
                account_type="express",
                is_default=True,
                verified_at=datetime.now(UTC),
            )
            session.add(payout_account)
            framework = Framework(
                contributor_id=contributor.id,
                title="Developer E2E Framework",
                description=(
                    "Framework used to verify the full Developer platform flow."
                ),
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["developer", "e2e"],
                tags_text="developer e2e",
                price=Decimal("1000.00"),
                currency="USD",
                license_types=["team"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            return {
                "admin_id": admin.id,
                "admin_totp_secret": admin_totp_secret,
                "developer_id": developer.id,
                "developer_totp_secret": developer_totp_secret,
                "contributor_id": contributor.id,
                "operator_id": operator.id,
                "operator_email": operator.email,
                "payout_account_id": payout_account.id,
                "framework_id": framework.id,
            }


def payment_intent_event(transaction_id: UUID, framework_id: UUID) -> dict[str, Any]:
    """Build a Stripe PaymentIntent success event for the E2E purchase."""
    return {
        "id": "evt_developer_e2e_purchase",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_developer_e2e",
                "metadata": {
                    "transaction_id": str(transaction_id),
                    "kind": "purchase",
                    "framework_id": str(framework_id),
                    "license_type": "team",
                },
            }
        },
    }


async def force_commission_past_clearing_delay(commission_id: UUID) -> None:
    """Move a pending commission past the 48-hour clearing delay."""
    async with async_session_factory() as session:
        async with session.begin():
            commission = await session.get(PartnerCommission, commission_id)
            assert commission is not None
            commission.created_at = datetime.now(UTC) - timedelta(hours=49)


async def deliver_and_verify_partner_webhook(
    delivery_id: str,
    raw_secret: str,
    captured: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deliver one queued Partner webhook and verify its HMAC signature."""

    async def fake_post_webhook(
        url: str,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> int:
        """Capture outbound webhook payloads without network access."""
        captured.append({"url": url, "raw_body": raw_body, "headers": headers})
        return 204

    monkeypatch.setattr(partner_webhooks, "_post_webhook", fake_post_webhook)
    result = await partner_webhooks._deliver_partner_webhook(delivery_id)

    sent = captured[-1]
    headers = sent["headers"]
    raw_body = sent["raw_body"]
    expected_signature = hmac.new(
        raw_secret.encode("utf-8"),
        f"{headers['X-Auracles-Timestamp']}.".encode() + raw_body,
        hashlib.sha256,
    ).hexdigest()
    assert result == {"delivery_id": delivery_id, "status": "delivered"}
    assert sent["url"] == "https://partner.example.com/auracles/webhooks"
    assert headers["X-Auracles-Signature"] == expected_signature


async def test_developer_platform_end_to_end_money_and_webhook_flow(
    client: AsyncClient,
    migrated_database: None,
    developer_e2e_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Developer can apply, sell through Partner API, clear, webhook, and payout."""
    del migrated_database
    users = await create_e2e_users()

    application = await client.post(
        "/v1/developer/applications",
        headers=auth_headers(users["developer_id"], []),
        json={
            "company_name": "Developer E2E Partner",
            "website": "https://partner.example.com",
            "use_case": "Embed Auracles Framework discovery and purchases in our CRM.",
        },
    )
    assert application.status_code == 201
    application_id = application.json()["id"]

    approved = await client.post(
        f"/v1/admin/developer/applications/{application_id}/review",
        headers=auth_headers(users["admin_id"], ["admin"]),
        json={
            "decision": "approved",
            "feedback": "Approved for E2E verification.",
            "totp_code": pyotp.TOTP(users["admin_totp_secret"]).now(),
        },
    )
    assert approved.status_code == 200

    key = await client.post(
        "/v1/developer/api-keys",
        headers=auth_headers(users["developer_id"], ["developer"]),
        json={
            "name": "E2E production key",
            "scopes": ["catalog:read", "purchase:write"],
        },
    )
    assert key.status_code == 201
    raw_api_key = key.json()["raw_key"]

    webhook = await client.post(
        "/v1/developer/webhooks",
        headers=auth_headers(users["developer_id"], ["developer"]),
        json={
            "url": "https://partner.example.com/auracles/webhooks",
            "events": ["purchase.confirmed", "commission.cleared"],
        },
    )
    assert webhook.status_code == 201
    raw_webhook_secret = webhook.json()["secret"]

    catalog = await client.get(
        "/v1/partner/catalog",
        headers={"X-API-Key": raw_api_key},
    )
    assert catalog.status_code == 200
    assert catalog.json()["items"][0]["id"] == str(users["framework_id"])

    purchase = await client.post(
        f"/v1/partner/frameworks/{users['framework_id']}/purchase",
        headers={"X-API-Key": raw_api_key},
        json={"buyer_email": users["operator_email"], "license_type": "team"},
    )
    assert purchase.status_code == 200
    transaction_id = UUID(purchase.json()["transaction_id"])

    developer_e2e_context["stripe_events"].append(
        payment_intent_event(transaction_id, users["framework_id"])
    )
    confirmed = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json() == {"received": True, "status": "processed"}

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        license_row = await session.scalar(
            select(License).where(License.transaction_id == transaction_id)
        )
        commission = await session.scalar(
            select(PartnerCommission).where(
                PartnerCommission.transaction_id == transaction_id
            )
        )
    assert transaction is not None
    assert transaction.status == "completed"
    assert license_row is not None
    assert commission is not None
    assert commission.status == "pending"
    assert commission.commission_amount == Decimal("50.00")
    assert developer_e2e_context["invoice_jobs"] == [str(transaction_id)]
    assert len(developer_e2e_context["dispatched_webhooks"]) == 1

    captured_webhooks: list[dict[str, Any]] = []
    await deliver_and_verify_partner_webhook(
        developer_e2e_context["dispatched_webhooks"][0],
        raw_webhook_secret,
        captured_webhooks,
        monkeypatch,
    )
    assert json.loads(captured_webhooks[-1]["raw_body"])["event"] == (
        "purchase.confirmed"
    )

    await force_commission_past_clearing_delay(commission.id)
    cleared = await developer_beat._clear_partner_commissions()
    assert cleared == {"cleared_count": 1, "voided_count": 0}
    assert len(developer_e2e_context["dispatched_webhooks"]) == 2
    await deliver_and_verify_partner_webhook(
        developer_e2e_context["dispatched_webhooks"][1],
        raw_webhook_secret,
        captured_webhooks,
        monkeypatch,
    )
    assert json.loads(captured_webhooks[-1]["raw_body"])["event"] == (
        "commission.cleared"
    )

    payout = await client.post(
        "/v1/developer/payouts",
        headers=auth_headers(users["developer_id"], ["developer"]),
        json={
            "amount": "50.00",
            "currency": "USD",
            "payout_account_id": str(users["payout_account_id"]),
            "totp_code": pyotp.TOTP(users["developer_totp_secret"]).now(),
        },
    )
    assert payout.status_code == 200
    assert payout.json()["amount"] == "50.00"
    assert payout.json()["status"] == "pending"
    assert developer_e2e_context["dispatched_payouts"] == [payout.json()["id"]]

    async with async_session_factory() as session:
        paid_commission = await session.get(PartnerCommission, commission.id)
        payout_row = await session.get(PartnerPayout, UUID(payout.json()["id"]))
    assert paid_commission is not None
    assert paid_commission.status == "cleared"
    assert paid_commission.payout_id == payout_row.id
    assert payout_row is not None
