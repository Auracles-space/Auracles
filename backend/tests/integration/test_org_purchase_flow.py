"""Integration tests for organization-payer Framework purchase and grant.

Task 5 of "Organizations as Operators": an org admin can start Stripe
checkout on behalf of the organization, and the Stripe webhook branch grants
an org-owned License that shows up in the org shared library for a granted
member.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import delete, select, update

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.integrations.paystack import PaystackInitializedTransaction
from app.main import app
from app.modules.auth.models import User
from app.modules.financials import service as financials_service
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework, License, LicenseGrant
from app.modules.invoicing.models import Invoice
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from app.modules.webhooks import service as webhook_service
from app.modules.webhooks.models import WebhookEvent
from app.shared.models.audit_log import AuditLog
from tests.conftest import open_step_up_window, verify_org_kyb
from tests.integration.test_financials_payment_methods import FakeRedis

pytestmark = pytest.mark.asyncio


class FakeStripePaymentIntent:
    """Small stand-in for a Stripe PaymentIntent result."""

    def __init__(self, payment_intent_id: str, client_secret: str) -> None:
        """Store the provider intent id and browser client secret."""
        self.id = payment_intent_id
        self.client_secret = client_secret


class FakeInvoiceTask:
    """Celery task double that records invoice generation requests."""

    def __init__(self) -> None:
        """Initialise the in-memory dispatch log."""
        self.dispatched: list[str] = []

    def delay(self, transaction_id: str) -> None:
        """Record the transaction id that would be sent to Celery."""
        self.dispatched.append(transaction_id)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure application tables exist for org purchase integration tests."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def org_purchase_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset org purchase rows and replace Stripe/webhook calls with doubles."""
    fake_redis = FakeRedis()
    calls: dict[str, list[Any]] = {"payment_intents": []}
    webhook_state: dict[str, Any] = {"event": None}

    await engine.dispose()

    async def cleanup() -> None:
        """Delete purchase, org, and identity rows in FK-safe order."""
        async with async_session_factory() as session:
            await session.execute(delete(WebhookEvent))
            await session.execute(delete(AuditLog))
            await session.execute(delete(LicenseGrant))
            await session.execute(delete(License))
            await session.execute(delete(Transaction))
            await session.execute(delete(Framework))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()

    async def fake_create_payment_intent(
        *,
        customer_id: str,
        amount: Decimal,
        currency: str,
        metadata: dict[str, str],
        idempotency_key: str | None = None,
    ) -> FakeStripePaymentIntent:
        """Record PaymentIntent creation and return a browser client secret."""
        calls["payment_intents"].append(
            {
                "customer_id": customer_id,
                "amount": amount,
                "currency": currency,
                "metadata": dict(metadata),
                "idempotency_key": idempotency_key,
            }
        )
        return FakeStripePaymentIntent("pi_org_purchase_123", "pi_org_secret_123")

    def fake_verify_webhook(
        payload: bytes,
        signature_header: str | None,
    ) -> dict[str, Any]:
        """Record raw body verification and return the configured event."""
        del payload
        if signature_header != "valid-signature":
            from app.integrations.stripe import StripeProviderError

            raise StripeProviderError("bad signature")
        event = webhook_state["event"]
        assert isinstance(event, dict)
        return event

    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr(
        financials_service.stripe,
        "create_payment_intent",
        fake_create_payment_intent,
    )
    monkeypatch.setattr(webhook_service.stripe, "verify_webhook", fake_verify_webhook)
    fake_invoice_task = FakeInvoiceTask()
    monkeypatch.setattr(
        webhook_service,
        "generate_invoice_pdf",
        fake_invoice_task,
        raising=False,
    )
    try:
        yield {
            "redis": fake_redis,
            "calls": calls,
            "webhook_state": webhook_state,
            "invoice_task": fake_invoice_task,
        }
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def _create_user(prefix: str) -> UUID:
    """Create one verified user and return its id."""
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status="verified",
                # Org checkout is step-up gated, so buyers are 2FA-enrolled.
                totp_enabled=True,
                totp_secret=encrypt_totp_secret("JBSWY3DPEHPK3PXP"),
            )
            session.add(user)
            await session.flush()
            return user.id


def _auth_headers(user_id: UUID) -> dict[str, str]:
    """Return bearer auth headers for one user."""
    token = create_access_token(user_id, [])
    return {"Authorization": f"Bearer {token}"}


async def _create_org(
    client: AsyncClient, owner_id: UUID, prefix: str
) -> dict[str, Any]:
    """Create one organization through the public org-create route."""
    response = await client.post(
        "/v1/orgs",
        json={"slug": f"{prefix}-{uuid4().hex[:6]}", "name": prefix, "country": "US"},
        headers=_auth_headers(owner_id),
    )
    assert response.status_code == 201
    # An unverified org is a shell; tests want a usable one.
    await verify_org_kyb((response.json())["id"])
    return response.json()


async def _add_member(org_id: UUID, user_id: UUID, *, role: str = "member") -> UUID:
    """Insert one org membership row directly and return its member id."""
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=org_id, user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            return member.id


async def _activate_operator_capability(
    client: AsyncClient, org_id: str, owner_id: UUID
) -> None:
    """Self-activate the org Operator capability via the API."""
    await verify_org_kyb(org_id)
    response = await client.post(
        f"/v1/orgs/{org_id}/operator-capability/activate",
        headers=_auth_headers(owner_id),
    )
    assert response.status_code == 200


async def _set_org_stripe_customer(org_id: str, customer_id: str | None) -> None:
    """Directly set an organization's Stripe customer id for test setup."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Organization)
                .where(Organization.id == UUID(org_id))
                .values(stripe_customer_id=customer_id)
            )


async def _suspend_operator_capability(org_id: str) -> None:
    """Directly mark the org Operator capability suspended for test setup."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(OrgCapability)
                .where(
                    OrgCapability.org_id == UUID(org_id),
                    OrgCapability.capability == "operator",
                )
                .values(status="suspended")
            )


async def _create_published_framework(
    contributor_id: UUID | None,
    *,
    contributor_org_id: UUID | None = None,
    price: Decimal = Decimal("249.00"),
    license_types: list[str] | None = None,
) -> UUID:
    """Create a published Framework available for org checkout."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                contributor_org_id=contributor_org_id,
                title="Org Purchase Flow Framework",
                description="A practical operating system for org buyers.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["org-purchase"],
                price=price,
                currency="USD",
                license_types=license_types or ["single_user", "team"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            return framework.id


async def test_org_purchase_happy_path_and_webhook_grants_org_library_access(
    client: AsyncClient,
    migrated_database: None,
    org_purchase_context: dict[str, Any],
) -> None:
    """Admin-initiated org checkout, on webhook success, grants library access."""
    del migrated_database
    contributor_id = await _create_user("org-purchase-contributor")
    owner_id = await _create_user("org-purchase-owner")
    member_id = await _create_user("org-purchase-member")
    org = await _create_org(client, owner_id, "org-purchase")
    await open_step_up_window(org_purchase_context["redis"], owner_id)
    member_row_id = await _add_member(UUID(org["id"]), member_id)
    await _activate_operator_capability(client, org["id"], owner_id)
    await _set_org_stripe_customer(org["id"], "cus_org_purchase_flow_123")
    framework_id = await _create_published_framework(contributor_id)

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/purchase",
        headers=_auth_headers(owner_id),
        json={"license_type": "team"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "stripe"
    assert body["client_secret"] == "pi_org_secret_123"
    transaction_id = UUID(body["transaction_id"])

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
    assert transaction is not None
    assert transaction.payer_org_id == UUID(org["id"])
    assert transaction.payer_id is None

    org_purchase_context["webhook_state"]["event"] = {
        "id": "evt_org_purchase_flow_success",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_org_purchase_123",
                "metadata": {
                    "transaction_id": str(transaction_id),
                    "kind": "purchase",
                    "framework_id": str(framework_id),
                    "license_type": "team",
                    "payer_org_id": org["id"],
                },
            }
        },
    }
    webhook_response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )
    assert webhook_response.status_code == 200
    assert webhook_response.json() == {"received": True, "status": "processed"}

    async with async_session_factory() as session:
        completed_transaction = await session.get(Transaction, transaction_id)
        license_row = await session.scalar(
            select(License).where(License.framework_id == framework_id)
        )
    assert completed_transaction is not None
    assert completed_transaction.status == "completed"
    assert license_row is not None
    assert license_row.licensee_org_id == UUID(org["id"])
    assert license_row.operator_id is None

    # Settlement issues the invoice under the org's own buyer identity and
    # queues its PDF, so the billing section lists it without anyone having
    # to request it first (FR-FIN-003 covers org purchases too).
    async with async_session_factory() as session:
        invoice = await session.scalar(
            select(Invoice).where(Invoice.source_ref_id == transaction_id)
        )
        owner = await session.get(User, owner_id)
    assert invoice is not None
    assert invoice.buyer_name == org["name"]
    assert owner is not None
    # No billing_email configured, so the buyer email falls back to the owner.
    assert invoice.buyer_email == owner.email
    assert org_purchase_context["invoice_task"].dispatched == [str(transaction_id)]

    grant_response = await client.post(
        f"/v1/orgs/{org['id']}/licenses/{license_row.id}/grants",
        json={"member_id": str(member_row_id)},
        headers=_auth_headers(owner_id),
    )
    assert grant_response.status_code == 201

    member_library = await client.get(
        f"/v1/orgs/{org['id']}/library",
        headers=_auth_headers(member_id),
    )
    assert member_library.status_code == 200
    items = member_library.json()["items"]
    assert len(items) == 1
    assert items[0]["license_id"] == str(license_row.id)


async def test_org_purchase_routes_to_paystack_for_nigerian_billing(
    client: AsyncClient,
    migrated_database: None,
    org_purchase_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Nigerian org checkout goes through Paystack hosted checkout.

    Paystack has no stored-payment-method concept, so the org needs no Stripe
    customer on file: the charge is initialized against the org's billing
    contact (falling back to the owner) and the browser is redirected.
    Enforces the org side of the Nigerian pilot corridor.
    """
    del migrated_database
    paystack_calls: list[dict[str, Any]] = []

    async def fake_initialize_transaction(
        *,
        email: str,
        amount: Decimal,
        currency: str,
        metadata: dict[str, str],
        callback_url: str | None = None,
    ) -> PaystackInitializedTransaction:
        """Record the Paystack charge initialization for the org purchase."""
        paystack_calls.append(
            {
                "email": email,
                "amount": amount,
                "currency": currency,
                "metadata": dict(metadata),
                "callback_url": callback_url,
            }
        )
        return PaystackInitializedTransaction(
            reference="auracles_org_ref_001",
            authorization_url="https://checkout.paystack.com/org_001",
            access_code="access_org_001",
        )

    monkeypatch.setattr(
        financials_service.paystack,
        "initialize_transaction",
        fake_initialize_transaction,
    )
    contributor_id = await _create_user("org-ngn-contributor")
    owner_id = await _create_user("org-ngn-owner")
    org = await _create_org(client, owner_id, "org-ngn-purchase")
    await open_step_up_window(org_purchase_context["redis"], owner_id)
    await _activate_operator_capability(client, org["id"], owner_id)
    # Deliberately no Stripe customer: the Paystack rail must not require one.
    framework_id = await _create_published_framework(contributor_id)

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/purchase",
        headers=_auth_headers(owner_id),
        json={"license_type": "team", "country": "NG"},
    )

    async with async_session_factory() as session:
        transaction = await session.scalar(
            select(Transaction).where(Transaction.payer_org_id == UUID(org["id"]))
        )
        owner = await session.get(User, owner_id)

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "paystack"
    assert body["authorization_url"] == "https://checkout.paystack.com/org_001"
    assert body["client_secret"] is None
    assert transaction is not None
    assert transaction.provider == "paystack"
    assert transaction.provider_ref == "auracles_org_ref_001"
    assert transaction.status == "pending"
    assert transaction.payer_id is None
    assert owner is not None
    initialized = paystack_calls[0]
    # No billing_email is configured, so the charge bills the org owner.
    assert initialized["email"] == owner.email
    assert initialized["metadata"]["kind"] == "purchase"
    assert initialized["metadata"]["transaction_id"] == str(transaction.id)
    assert initialized["metadata"]["payer_org_id"] == org["id"]
    # An org buyer's Library lives in the org workspace, so the Paystack
    # callback must return there rather than to the personal /library.
    assert initialized["callback_url"] == (
        f"http://localhost:3000/dashboard/organizations/{org['id']}"
        f"/operator/library?purchase={transaction.id}"
    )


async def test_org_purchase_requires_auth_and_admin_role(
    client: AsyncClient,
    migrated_database: None,
    org_purchase_context: dict[str, Any],
) -> None:
    """Unauthenticated and plain-member callers cannot start org checkout."""
    del migrated_database
    contributor_id = await _create_user("org-purchase-contributor")
    owner_id = await _create_user("org-purchase-owner")
    member_id = await _create_user("org-purchase-member")
    org = await _create_org(client, owner_id, "org-purchase")
    await open_step_up_window(org_purchase_context["redis"], owner_id)
    await _add_member(UUID(org["id"]), member_id)
    await _activate_operator_capability(client, org["id"], owner_id)
    await _set_org_stripe_customer(org["id"], "cus_org_purchase_flow_123")
    framework_id = await _create_published_framework(contributor_id)

    unauthenticated = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/purchase",
        json={"license_type": "single_user"},
    )
    forbidden = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/purchase",
        headers=_auth_headers(member_id),
        json={"license_type": "single_user"},
    )

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403


async def test_org_purchase_blocks_suspended_capability(
    client: AsyncClient,
    migrated_database: None,
    org_purchase_context: dict[str, Any],
) -> None:
    """A suspended Operator capability blocks org checkout with 403."""
    del migrated_database
    contributor_id = await _create_user("org-purchase-contributor")
    owner_id = await _create_user("org-purchase-owner")
    org = await _create_org(client, owner_id, "org-purchase")
    await open_step_up_window(org_purchase_context["redis"], owner_id)
    await _activate_operator_capability(client, org["id"], owner_id)
    await _set_org_stripe_customer(org["id"], "cus_org_purchase_flow_123")
    await _suspend_operator_capability(org["id"])
    framework_id = await _create_published_framework(contributor_id)

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/purchase",
        headers=_auth_headers(owner_id),
        json={"license_type": "single_user"},
    )

    assert response.status_code == 403


async def test_org_purchase_requires_payment_method_on_file(
    client: AsyncClient,
    migrated_database: None,
    org_purchase_context: dict[str, Any],
) -> None:
    """An org with no Stripe customer on file gets 402, not a Stripe call."""
    del migrated_database
    contributor_id = await _create_user("org-purchase-contributor")
    owner_id = await _create_user("org-purchase-owner")
    org = await _create_org(client, owner_id, "org-purchase")
    await open_step_up_window(org_purchase_context["redis"], owner_id)
    await _activate_operator_capability(client, org["id"], owner_id)
    framework_id = await _create_published_framework(contributor_id)

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/purchase",
        headers=_auth_headers(owner_id),
        json={"license_type": "single_user"},
    )

    assert response.status_code == 402
    assert org_purchase_context["calls"]["payment_intents"] == []


async def test_org_purchase_rejects_self_deal(
    client: AsyncClient,
    migrated_database: None,
    org_purchase_context: dict[str, Any],
) -> None:
    """An org cannot purchase a Framework it sells itself."""
    del migrated_database
    owner_id = await _create_user("org-purchase-owner")
    org = await _create_org(client, owner_id, "org-purchase")
    await open_step_up_window(org_purchase_context["redis"], owner_id)
    await _activate_operator_capability(client, org["id"], owner_id)
    await _set_org_stripe_customer(org["id"], "cus_org_purchase_flow_123")
    framework_id = await _create_published_framework(
        None,
        contributor_org_id=UUID(org["id"]),
    )

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/purchase",
        headers=_auth_headers(owner_id),
        json={"license_type": "single_user"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "self_deal_conflict"
    assert org_purchase_context["calls"]["payment_intents"] == []
