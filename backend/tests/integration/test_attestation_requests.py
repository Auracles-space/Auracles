"""Integration tests for Phase 4b Attestation request funding."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.integrations import paystack, stripe
from app.integrations.paystack import PaystackInitializedTransaction
from app.main import app
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestationUploadSession,
    Credential,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.modules.frameworks.models import Framework, FrameworkVersion
from app.modules.webhooks.models import WebhookEvent
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for routes that do not use Redis directly."""

    def __init__(self) -> None:
        """Create empty in-memory Redis-like state."""
        self.values: dict[str, str] = {}
        self.counters: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored string or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool:
        """Store a string value, optionally respecting NX semantics."""
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a string value with a TTL (test double ignores expiry)."""
        del seconds
        self.values[key] = value

    async def incr(self, key: str) -> int:
        """Increment and return a counter value."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """No-op TTL assignment for the test double."""
        del key, seconds

    async def delete(self, *keys: str) -> int:
        """Delete string and counter keys."""
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.counters)
            self.values.pop(key, None)
            self.counters.pop(key, None)
        return removed

    async def ttl(self, key: str) -> int:
        """Return the no-expiry sentinel."""
        del key
        return -1


class FakeStripePaymentIntent:
    """Small stand-in for a Stripe PaymentIntent result."""

    def __init__(self, payment_intent_id: str, client_secret: str) -> None:
        """Store fake provider identifiers."""
        self.id = payment_intent_id
        self.client_secret = client_secret


class FakeStripeCustomer:
    """Small stand-in for a Stripe Customer result."""

    def __init__(self, customer_id: str) -> None:
        """Store fake provider customer id."""
        self.id = customer_id


class FakeNotificationTask:
    """Celery-task-shaped test double for attestation notifications."""

    def __init__(self, calls: list[dict[str, Any]]) -> None:
        """Store delayed notification dispatches in the provided list."""
        self.calls = calls

    def delay(self, **kwargs: Any) -> None:
        """Capture notification dispatch parameters without Redis or email."""
        self.calls.append(kwargs)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Phase 4b attestation tables exist for endpoint tests."""
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
async def attestation_context() -> AsyncIterator[FakeRedis]:
    """Reset attestation/auth/financial state and install Redis test double."""
    fake_redis = FakeRedis()
    await engine.dispose()
    await reset_attestation_state()

    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await reset_attestation_state()
        await engine.dispose()


async def reset_attestation_state() -> None:
    """Remove attestation request test rows in dependency order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(WebhookEvent))
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(AttestationDispute))
            await session.execute(delete(Attestation))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(Credential))
            await session.execute(delete(FrameworkVersion))
            await session.execute(delete(Framework))
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            for key, value in {
                "attestation_fee_framework": "250.00",
                "attestation_fee_contributor": "300.00",
                "attestation_fee_operator": "300.00",
                "attestation_fee_credential": "100.00",
                "attestation_fee_review_quality": "500.00",
                "attestation_fee_review_compliance": "1200.00",
                "attestation_fee_review_expert": "2500.00",
                "attestation_fee_review_provenance": "500.00",
                "attestation_completion_sla_days_framework": "10",
                "attestation_completion_sla_days_contributor": "10",
                "attestation_completion_sla_days_operator": "10",
                "attestation_completion_sla_days_credential": "10",
            }.items():
                row = await session.get(PlatformConfig, key)
                if row is None:
                    session.add(PlatformConfig(key=key, value=value))
                else:
                    row.value = value


async def create_user(email: str, roles: list[str]) -> UUID:
    """Create a verified user with approved role rows."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            for role in roles:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        approved_at=datetime.now(UTC),
                    )
                )
        return user.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def create_credential(owner_id: UUID) -> UUID:
    """Create one Credential owned by a test user."""
    async with async_session_factory() as session:
        async with session.begin():
            credential = Credential(
                user_id=owner_id,
                title="Certified Transformation Lead",
                issuer="Global Institute",
                issued_date=datetime(2024, 1, 1, tzinfo=UTC).date(),
            )
            session.add(credential)
            await session.flush()
            return credential.id


async def create_attestation_row(
    *,
    requestor_id: UUID,
    target_id: UUID,
    status: str = "matching",
) -> UUID:
    """Create one Attestation row for requestor list endpoint tests."""
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="credential",
                target_id=target_id,
                requestor_id=requestor_id,
                status=status,
                requested_specializations=["governance"],
                requested_jurisdictions=["US"],
                fee_amount=Decimal("100.00"),
                currency="USD",
            )
            session.add(attestation)
            await session.flush()
            return attestation.id


async def _stub_stripe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch Stripe customer and PaymentIntent creation with test doubles."""

    async def fake_create_customer(
        *,
        email: str,
        name: str | None = None,
        idempotency_key: str | None = None,
    ) -> FakeStripeCustomer:
        """Return a deterministic fake Stripe customer."""
        del email, name, idempotency_key
        return FakeStripeCustomer("cus_framework_attestation")

    async def fake_create_payment_intent(
        *,
        customer_id: str,
        amount: Decimal,
        currency: str,
        metadata: Mapping[str, str],
        idempotency_key: str | None = None,
    ) -> FakeStripePaymentIntent:
        """Return a deterministic fake Stripe PaymentIntent."""
        del customer_id, amount, currency, metadata, idempotency_key
        return FakeStripePaymentIntent(
            "pi_framework_attestation",
            "pi_framework_attestation_secret",
        )

    async def fake_retrieve_payment_intent(
        payment_intent_id: str,
        *,
        settings: object | None = None,
        client: object | None = None,
    ) -> FakeStripePaymentIntent:
        """Return the fake PaymentIntent for a stored provider ref."""
        del settings, client
        return FakeStripePaymentIntent(
            payment_intent_id,
            f"{payment_intent_id}_secret",
        )

    monkeypatch.setattr(stripe, "create_customer", fake_create_customer)
    monkeypatch.setattr(stripe, "create_payment_intent", fake_create_payment_intent)
    monkeypatch.setattr(stripe, "retrieve_payment_intent", fake_retrieve_payment_intent)


async def _create_framework(owner_id: UUID, status_value: str = "published") -> UUID:
    """Create a Framework row that satisfies current model requirements."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=owner_id,
                title="KYC Onboarding Framework",
                description="Standardises KYC onboarding for operators.",
                status=status_value,
                category="compliance",
                tags=["kyc", "aml"],
                price=Decimal("199.00"),
                license_types=["single_user"],
            )
            session.add(framework)
            await session.flush()
            return framework.id


_FRAMEWORK_BRIEF = {
    "what_it_does": "Standardises KYC onboarding",
    "use_case": "Compliance team at a mid-size fund",
    "jurisdiction": "US",
    "focus_areas": "AML completeness",
    "desired_outcome": "Compliance sign-off badge",
}


async def test_attestation_fee_resolves_by_review_type(
    migrated_database: None,
    attestation_context: FakeRedis,
) -> None:
    """Framework fees follow the review tier; other targets keep flat fees."""
    del migrated_database, attestation_context
    from app.core.database import async_session_factory
    from app.modules.attestation.service import _attestation_fee

    async with async_session_factory() as session:
        assert await _attestation_fee(session, "framework", "quality") == Decimal(
            "500.00"
        )
        assert await _attestation_fee(session, "framework", "compliance") == Decimal(
            "1200.00"
        )
        assert await _attestation_fee(session, "framework", "expert") == Decimal(
            "2500.00"
        )
        assert await _attestation_fee(session, "framework", "provenance") == Decimal(
            "500.00"
        )
        assert await _attestation_fee(session, "contributor", None) == Decimal("300.00")
        assert await _attestation_fee(session, "operator", "expert") == Decimal(
            "300.00"
        )
        assert await _attestation_fee(session, "credential", "quality") == Decimal(
            "100.00"
        )


def test_attestation_brief_rejects_blank_fields() -> None:
    """A brief with an empty required field fails Pydantic validation."""
    from pydantic import ValidationError

    from app.modules.attestation.schemas import AttestationBrief

    with pytest.raises(ValidationError):
        AttestationBrief(
            what_it_does="",
            use_case="growth team",
            jurisdiction="US",
            focus_areas="AML coverage",
            desired_outcome="compliance sign-off",
        )


def test_attestation_request_accepts_review_type_and_brief() -> None:
    """The create schema accepts a review_type and a structured brief."""
    from app.modules.attestation.schemas import AttestationRequestCreateRequest

    payload = AttestationRequestCreateRequest(
        target_type="framework",
        target_id="11111111-1111-1111-1111-111111111111",
        review_type="compliance",
        brief={
            "what_it_does": "Standardises KYC onboarding",
            "use_case": "Compliance team at a mid-size fund",
            "jurisdiction": "US",
            "focus_areas": "AML completeness",
            "desired_outcome": "Compliance sign-off badge",
        },
        requested_specializations=["compliance"],
        requested_jurisdictions=["US"],
    )
    assert payload.review_type == "compliance"
    assert payload.brief is not None
    assert payload.brief.jurisdiction == "US"


async def test_framework_request_persists_review_type_and_brief(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A framework attestation stores review_type, brief, and audit flags."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    contributor_id = await create_user("fw-owner@auracles.space", ["contributor"])
    framework_id = await _create_framework(contributor_id)

    response = await client.post(
        "/v1/attestations",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "compliance",
            "brief": _FRAMEWORK_BRIEF,
            "requested_specializations": ["compliance"],
            "requested_jurisdictions": ["US"],
        },
    )

    assert response.status_code == 201
    attestation_id = UUID(response.json()["id"])
    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attestation_requested",
                AuditLog.target_id == attestation_id,
            )
        )

    assert attestation is not None
    assert attestation.review_type == "compliance"
    assert attestation.brief == _FRAMEWORK_BRIEF
    assert attestation.fee_amount == Decimal("1200.00")
    assert audit is not None
    assert audit.metadata_["review_type"] == "compliance"
    assert audit.metadata_["brief_provided"] is True
    assert audit.metadata_["initiator_is_owner"] is True


async def test_nigerian_requestor_funds_attestation_on_paystack(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A requestor in Nigeria pays the Attestation fee via Paystack checkout.

    Mirrors the milestone-funding corridor: the response carries a redirect
    `authorization_url` and no client secret, no Stripe customer is created,
    and the charge metadata carries the escrow kind the webhook settles on.
    Enforces FR-FIN-006 on the Paystack rail.
    """
    del migrated_database, attestation_context
    calls: dict[str, list[Any]] = {"customers": [], "paystack_transactions": []}

    async def fail_create_customer(**kwargs: Any) -> FakeStripeCustomer:
        """Fail the test if the Paystack rail touches Stripe."""
        calls["customers"].append(kwargs)
        raise AssertionError("Stripe customer must not be created on Paystack rail")

    async def fake_initialize_transaction(
        *,
        email: str,
        amount: Decimal,
        currency: str,
        metadata: Mapping[str, str],
        callback_url: str | None = None,
    ) -> PaystackInitializedTransaction:
        """Record the Paystack charge initialization for the fee."""
        calls["paystack_transactions"].append(
            {
                "email": email,
                "amount": amount,
                "currency": currency,
                "metadata": dict(metadata),
                "callback_url": callback_url,
            }
        )
        return PaystackInitializedTransaction(
            reference="auracles_attestation_ref_001",
            authorization_url="https://checkout.paystack.com/attestation_001",
            access_code="access_attestation_001",
        )

    monkeypatch.setattr(stripe, "create_customer", fail_create_customer)
    monkeypatch.setattr(
        paystack,
        "initialize_transaction",
        fake_initialize_transaction,
    )

    contributor_id = await create_user("ngn-fee-owner@auracles.space", ["contributor"])
    framework_id = await _create_framework(contributor_id)

    response = await client.post(
        "/v1/attestations",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "compliance",
            "brief": _FRAMEWORK_BRIEF,
            "country": "NG",
        },
    )

    async with async_session_factory() as session:
        transaction = await session.scalar(select(Transaction))
        requestor = await session.get(User, contributor_id)

    assert response.status_code == 201
    body = response.json()
    assert body["provider"] == "paystack"
    assert body["authorization_url"] == (
        "https://checkout.paystack.com/attestation_001"
    )
    assert body["client_secret"] is None
    assert transaction is not None
    assert transaction.provider == "paystack"
    assert transaction.provider_ref == "auracles_attestation_ref_001"
    assert transaction.status == "pending"
    assert transaction.transaction_type == "attestation_fee"
    assert transaction.amount == Decimal("1200.00")
    assert requestor is not None
    assert requestor.stripe_customer_id is None
    assert calls["customers"] == []
    initialized = calls["paystack_transactions"][0]
    assert initialized["email"] == "ngn-fee-owner@auracles.space"
    assert initialized["amount"] == Decimal("1200.00")
    assert initialized["metadata"]["kind"] == "escrow"
    assert initialized["metadata"]["transaction_id"] == str(transaction.id)
    assert initialized["metadata"]["attestation_id"] == body["id"]
    # Without a callback URL Paystack keeps the payer on its own success page,
    # so a paid requestor never returns to the Attestation and can pay twice.
    assert initialized["callback_url"] == (
        f"http://localhost:3000/attestations/{body['id']}?funded=1"
    )


async def test_paystack_fee_payment_reinitializes_hosted_checkout(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resuming a Paystack fee payment issues a fresh hosted checkout.

    Paystack cannot re-serve an old authorization URL, so the payment endpoint
    re-initializes the charge and the stored provider reference moves to the
    new attempt — the webhook then settles whichever reference is current.
    """
    del migrated_database, attestation_context
    references = iter(["auracles_attestation_ref_001", "auracles_attestation_ref_002"])

    async def fake_initialize_transaction(
        **kwargs: Any,
    ) -> PaystackInitializedTransaction:
        """Hand out a new reference per initialization."""
        reference = next(references)
        return PaystackInitializedTransaction(
            reference=reference,
            authorization_url=f"https://checkout.paystack.com/{reference}",
            access_code=f"access_{reference}",
        )

    monkeypatch.setattr(
        paystack,
        "initialize_transaction",
        fake_initialize_transaction,
    )

    contributor_id = await create_user("ngn-fee-resume@auracles.space", ["contributor"])
    framework_id = await _create_framework(contributor_id)
    created = await client.post(
        "/v1/attestations",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "compliance",
            "brief": _FRAMEWORK_BRIEF,
            "country": "NG",
        },
    )
    assert created.status_code == 201
    attestation_id = created.json()["id"]

    resumed = await client.get(
        f"/v1/attestations/{attestation_id}/payment",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    async with async_session_factory() as session:
        transaction = await session.scalar(select(Transaction))

    assert resumed.status_code == 200
    body = resumed.json()
    assert body["provider"] == "paystack"
    assert body["authorization_url"] == (
        "https://checkout.paystack.com/auracles_attestation_ref_002"
    )
    assert body["client_secret"] is None
    assert transaction is not None
    assert transaction.provider_ref == "auracles_attestation_ref_002"


async def test_pending_fee_request_returns_resumable_payment_secret(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The payment endpoint re-returns the existing PaymentIntent secret."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    contributor_id = await create_user("resume-fee@auracles.space", ["contributor"])
    framework_id = await _create_framework(contributor_id)

    created = await client.post(
        "/v1/attestations",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "compliance",
            "brief": _FRAMEWORK_BRIEF,
        },
    )
    assert created.status_code == 201
    attestation_id = created.json()["id"]

    resumed = await client.get(
        f"/v1/attestations/{attestation_id}/payment",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert resumed.status_code == 200
    body = resumed.json()
    assert body["id"] == attestation_id
    assert body["client_secret"] == "pi_framework_attestation_secret"


async def test_payment_secret_denied_to_non_owner(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user who does not own the request cannot fetch its payment secret."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    contributor_id = await create_user("owner-fee@auracles.space", ["contributor"])
    intruder_id = await create_user("intruder-fee@auracles.space", ["contributor"])
    framework_id = await _create_framework(contributor_id)

    created = await client.post(
        "/v1/attestations",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "compliance",
            "brief": _FRAMEWORK_BRIEF,
        },
    )
    assert created.status_code == 201
    attestation_id = created.json()["id"]

    denied = await client.get(
        f"/v1/attestations/{attestation_id}/payment",
        headers=auth_headers(intruder_id, ["contributor"]),
    )

    assert denied.status_code == 404


async def test_framework_request_requires_review_type_and_brief(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A framework request missing review_type and brief must fail with 422."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    contributor_id = await create_user("fw-owner-2@auracles.space", ["contributor"])
    framework_id = await _create_framework(contributor_id)

    response = await client.post(
        "/v1/attestations",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "requested_specializations": ["compliance"],
            "requested_jurisdictions": ["US"],
        },
    )

    assert response.status_code == 422


async def test_framework_request_needs_no_specializations(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A framework request succeeds without requester-typed matching lists."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    contributor_id = await create_user(
        "fw-owner-no-lists@auracles.space",
        ["contributor"],
    )
    framework_id = await _create_framework(contributor_id)

    response = await client.post(
        "/v1/attestations",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "compliance",
            "brief": _FRAMEWORK_BRIEF,
        },
    )

    assert response.status_code == 201


async def test_non_framework_request_still_requires_specializations(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-framework targets still require explicit matching lists."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    operator_id = await create_user(
        "credential-requestor-no-lists@auracles.space",
        ["operator"],
    )
    credential_id = await create_credential(operator_id)

    response = await client.post(
        "/v1/attestations",
        headers=auth_headers(operator_id, ["operator"]),
        json={
            "target_type": "credential",
            "target_id": str(credential_id),
        },
    )

    assert response.status_code == 422


async def test_operator_can_request_on_published_framework_they_dont_own(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator may request attestation on a published framework they do not own."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    owner_id = await create_user("fw-author@auracles.space", ["contributor"])
    operator_id = await create_user("fw-buyer@auracles.space", ["operator"])
    framework_id = await _create_framework(owner_id, "published")

    response = await client.post(
        "/v1/attestations",
        headers=auth_headers(operator_id, ["operator"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "quality",
            "brief": _FRAMEWORK_BRIEF,
            "requested_specializations": ["operations"],
            "requested_jurisdictions": ["US"],
        },
    )

    assert response.status_code == 201


async def test_operator_initiated_request_enters_consent_unpaid(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-owner framework request waits for owner consent before funding."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    owner_id = await create_user("fw-author-consent@auracles.space", ["contributor"])
    operator_id = await create_user("fw-buyer-consent@auracles.space", ["operator"])
    framework_id = await _create_framework(owner_id, "published")

    response = await client.post(
        "/v1/attestations",
        headers=auth_headers(operator_id, ["operator"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "quality",
            "brief": _FRAMEWORK_BRIEF,
            "requested_specializations": ["operations"],
            "requested_jurisdictions": ["US"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending_owner_consent"
    assert "client_secret" not in body

    async with async_session_factory() as session:
        transaction = await session.scalar(
            select(Transaction).where(Transaction.ref_id == UUID(body["id"]))
        )

    assert transaction is None


async def test_requestor_cancels_own_request_awaiting_owner_consent(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A requestor can abandon their own request while it awaits consent.

    Nothing has been charged at ``pending_owner_consent`` — no Transaction
    exists yet — so withdrawing is a pure state change with no money to
    unwind.
    """
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    owner_id = await create_user("fw-author-cancel@auracles.space", ["contributor"])
    operator_id = await create_user("fw-buyer-cancel@auracles.space", ["operator"])
    framework_id = await _create_framework(owner_id, "published")
    operator_headers = auth_headers(operator_id, ["operator"])

    created = await client.post(
        "/v1/attestations",
        headers=operator_headers,
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "quality",
            "brief": _FRAMEWORK_BRIEF,
            "requested_specializations": ["operations"],
            "requested_jurisdictions": ["US"],
        },
    )
    attestation_id = created.json()["id"]

    response = await client.post(
        f"/v1/attestations/{attestation_id}/cancel",
        headers=operator_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


async def test_requestor_cannot_cancel_once_the_fee_is_payable(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Withdrawing must stop at the point money can already be in flight.

    The fee webhook rejects any Attestation that has left ``pending_fee``, so
    allowing a withdrawal here would let a payment land against a cancelled
    request and strand the held funds.
    """
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    contributor_id = await create_user("fw-own-cancel@auracles.space", ["contributor"])
    framework_id = await _create_framework(contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])

    created = await client.post(
        "/v1/attestations",
        headers=headers,
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "quality",
            "brief": _FRAMEWORK_BRIEF,
        },
    )
    attestation_id = created.json()["id"]

    response = await client.post(
        f"/v1/attestations/{attestation_id}/cancel",
        headers=headers,
    )

    assert response.status_code == 409

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, UUID(attestation_id))

    assert attestation is not None
    assert attestation.status == "pending_fee"


async def test_requestor_cannot_cancel_another_users_request(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stranger withdrawing someone else's request gets a 404, not a 403.

    A 403 would confirm the Attestation exists to a caller with no claim on it.
    """
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    owner_id = await create_user("fw-author-idor@auracles.space", ["contributor"])
    operator_id = await create_user("fw-buyer-idor@auracles.space", ["operator"])
    stranger_id = await create_user("fw-stranger-idor@auracles.space", ["operator"])
    framework_id = await _create_framework(owner_id, "published")

    created = await client.post(
        "/v1/attestations",
        headers=auth_headers(operator_id, ["operator"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "quality",
            "brief": _FRAMEWORK_BRIEF,
            "requested_specializations": ["operations"],
            "requested_jurisdictions": ["US"],
        },
    )
    attestation_id = created.json()["id"]

    response = await client.post(
        f"/v1/attestations/{attestation_id}/cancel",
        headers=auth_headers(stranger_id, ["operator"]),
    )

    assert response.status_code == 404

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, UUID(attestation_id))

    assert attestation is not None
    assert attestation.status == "pending_owner_consent"


async def test_operator_cannot_request_on_unpublished_framework(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-owner requesting on an unpublished framework gets a 404."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    owner_id = await create_user("fw-author-2@auracles.space", ["contributor"])
    operator_id = await create_user("fw-buyer-2@auracles.space", ["operator"])
    framework_id = await _create_framework(owner_id, "draft")

    response = await client.post(
        "/v1/attestations",
        headers=auth_headers(operator_id, ["operator"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "quality",
            "brief": _FRAMEWORK_BRIEF,
            "requested_specializations": ["operations"],
            "requested_jurisdictions": ["US"],
        },
    )

    assert response.status_code == 404


async def test_review_types_list_labels_descriptions_and_fees(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
) -> None:
    """The request form reads each review type's description and live fee.

    Public: the fee is shown before a requestor commits, and the values come
    from platform config so an admin repricing shows up immediately.
    """
    del migrated_database, attestation_context

    response = await client.get("/v1/attestations/review-types")

    assert response.status_code == 200
    items = {item["key"]: item for item in response.json()["review_types"]}
    assert list(items) == ["quality", "compliance", "expert", "provenance"]
    assert items["quality"]["label"] == "Quality"
    assert items["quality"]["fee_amount"] == "500.00"
    assert items["compliance"]["fee_amount"] == "1200.00"
    assert items["quality"]["currency"]
    for item in items.values():
        assert item["description"].strip()


async def _settle_review_on_current_version(
    framework_id: UUID, requestor_id: UUID, review_type: str
) -> None:
    """Record a released attestation of ``review_type`` on the current version."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = await session.get(Framework, framework_id)
            assert framework is not None
            version = FrameworkVersion(
                framework_id=framework_id,
                version=framework.version,
                change_type="major",
                change_log="Initial release.",
                published_at=datetime.now(UTC),
            )
            session.add(version)
            await session.flush()
            session.add(
                Attestation(
                    target_type="framework",
                    target_id=framework_id,
                    requestor_id=requestor_id,
                    status="released",
                    outcome="conditional",
                    review_type=review_type,
                    brief=_FRAMEWORK_BRIEF,
                    requested_specializations=["compliance"],
                    requested_jurisdictions=["US"],
                    fee_amount=Decimal("500.00"),
                    currency="USD",
                    framework_version_id=version.id,
                )
            )


async def test_review_type_already_attested_on_this_version_is_refused(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A settled review type cannot be bought again for the same version.

    Human decision 2026-09-15: re-attesting a review type makes sense only for a
    newer version; other review types stay open.
    """
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    contributor_id = await create_user("fw-attested@auracles.space", ["contributor"])
    framework_id = await _create_framework(contributor_id)
    await _settle_review_on_current_version(framework_id, contributor_id, "quality")
    headers = auth_headers(contributor_id, ["contributor"])
    base_payload = {
        "target_type": "framework",
        "target_id": str(framework_id),
        "brief": _FRAMEWORK_BRIEF,
        "requested_specializations": ["compliance"],
        "requested_jurisdictions": ["US"],
    }

    again = await client.post(
        "/v1/attestations",
        headers=headers,
        json={**base_payload, "review_type": "quality"},
    )
    other = await client.post(
        "/v1/attestations",
        headers=headers,
        json={**base_payload, "review_type": "compliance"},
    )

    assert again.status_code == 409
    assert again.json()["detail"]["error_code"] == "review_type_already_attested"
    assert other.status_code == 201


async def test_review_type_can_be_attested_again_on_a_newer_version(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once the framework moves to a new version, the review type reopens."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    contributor_id = await create_user("fw-reattest@auracles.space", ["contributor"])
    framework_id = await _create_framework(contributor_id)
    await _settle_review_on_current_version(framework_id, contributor_id, "quality")
    async with async_session_factory() as session:
        async with session.begin():
            framework = await session.get(Framework, framework_id)
            assert framework is not None
            framework.version = "2.0.0"

    response = await client.post(
        "/v1/attestations",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "target_type": "framework",
            "target_id": str(framework_id),
            "review_type": "quality",
            "brief": _FRAMEWORK_BRIEF,
            "requested_specializations": ["compliance"],
            "requested_jurisdictions": ["US"],
        },
    )

    assert response.status_code == 201


async def test_same_target_different_review_type_allowed(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Different review types on the same framework are independent requests."""
    del migrated_database, attestation_context
    await _stub_stripe(monkeypatch)
    contributor_id = await create_user("fw-multi@auracles.space", ["contributor"])
    framework_id = await _create_framework(contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    base_payload = {
        "target_type": "framework",
        "target_id": str(framework_id),
        "brief": _FRAMEWORK_BRIEF,
        "requested_specializations": ["compliance"],
        "requested_jurisdictions": ["US"],
    }

    first = await client.post(
        "/v1/attestations",
        headers=headers,
        json={**base_payload, "review_type": "quality"},
    )
    second = await client.post(
        "/v1/attestations",
        headers=headers,
        json={**base_payload, "review_type": "compliance"},
    )
    duplicate = await client.post(
        "/v1/attestations",
        headers=headers,
        json={**base_payload, "review_type": "quality"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert duplicate.status_code == 409


async def test_owner_not_notified_again_on_operator_initiated_funding(
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Funding after owner consent must not notify the framework owner again."""
    del migrated_database, attestation_context
    from app.modules.attestation import notifications
    from app.modules.webhooks import service as webhook_service

    notification_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        notifications,
        "dispatch_project_notification",
        FakeNotificationTask(notification_calls),
    )

    async def fake_offer_next_cohort(*args: Any, **kwargs: Any) -> list[object]:
        """Keep the test focused on owner notification, not cohort matching."""
        del args, kwargs
        return []

    monkeypatch.setattr(
        webhook_service.matching_service,
        "offer_next_cohort",
        fake_offer_next_cohort,
    )

    owner_id = await create_user("fw-owner-notify@auracles.space", ["contributor"])
    operator_id = await create_user("fw-buyer-notify@auracles.space", ["operator"])
    framework_id = await _create_framework(owner_id, "published")

    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="framework",
                target_id=framework_id,
                requestor_id=operator_id,
                status="pending_fee",
                review_type="quality",
                brief=_FRAMEWORK_BRIEF,
                requested_specializations=["operations"],
                requested_jurisdictions=["US"],
                fee_amount=Decimal("500.00"),
                currency="USD",
            )
            session.add(attestation)
            await session.flush()
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=None,
                amount=Decimal("500.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("500.00"),
                transaction_type="attestation_fee",
                status="completed",
                provider="stripe",
                provider_ref="pi_owner_notify",
                ref_id=attestation.id,
                ref_type="attestation",
            )
            session.add(transaction)
            await session.flush()
            escrow = Escrow(
                ref_id=attestation.id,
                ref_type="attestation",
                amount=Decimal("500.00"),
                currency="USD",
                status="held",
                release_conditions={},
                transaction_id=transaction.id,
            )
            session.add(escrow)
            await session.flush()
            transaction_id = transaction.id
            escrow_id = escrow.id

    async with async_session_factory() as session:
        async with session.begin():
            transaction = await session.get(Transaction, transaction_id)
            escrow = await session.get(Escrow, escrow_id)
            assert transaction is not None
            assert escrow is not None
            callbacks = await webhook_service._mark_attestation_fee_funded(
                db=session,
                transaction=transaction,
                escrow=escrow,
            )

    for callback in callbacks:
        callback()

    owner_notifications = [
        call for call in notification_calls if call["user_id"] == str(owner_id)
    ]
    assert owner_notifications == []


async def test_requestor_lists_only_their_attestations(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
) -> None:
    """Requestors can list their own Attestation history through the API."""
    del migrated_database, attestation_context
    operator_id = await create_user("requestor-list@auracles.space", ["operator"])
    other_operator_id = await create_user(
        "other-requestor-list@auracles.space",
        ["operator"],
    )
    credential_id = await create_credential(operator_id)
    other_credential_id = await create_credential(other_operator_id)
    attestation_id = await create_attestation_row(
        requestor_id=operator_id,
        target_id=credential_id,
    )
    await create_attestation_row(
        requestor_id=other_operator_id,
        target_id=other_credential_id,
    )

    response = await client.get(
        "/v1/attestations",
        params={"role": "requestor"},
        headers=auth_headers(operator_id, ["operator"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["attestations"]] == [str(attestation_id)]
    assert body["attestations"][0]["requestor_id"] == str(operator_id)


async def test_operator_requests_credential_attestation_with_stripe_escrow(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requesting attestation creates pending fee transaction and Stripe intent."""
    del migrated_database, attestation_context
    stripe_calls: dict[str, list[object]] = {"customers": [], "payment_intents": []}

    async def fake_create_customer(
        *,
        email: str,
        name: str | None = None,
        idempotency_key: str | None = None,
    ) -> FakeStripeCustomer:
        """Record customer creation and return a fake Stripe customer."""
        stripe_calls["customers"].append(
            {"email": email, "name": name, "idempotency_key": idempotency_key}
        )
        return FakeStripeCustomer("cus_attestation_123")

    async def fake_create_payment_intent(
        *,
        customer_id: str,
        amount: Decimal,
        currency: str,
        metadata: Mapping[str, str],
        idempotency_key: str | None = None,
    ) -> FakeStripePaymentIntent:
        """Record PaymentIntent creation and return a browser client secret."""
        stripe_calls["payment_intents"].append(
            {
                "customer_id": customer_id,
                "amount": amount,
                "currency": currency,
                "metadata": dict(metadata),
                "idempotency_key": idempotency_key,
            }
        )
        return FakeStripePaymentIntent("pi_attestation_123", "pi_attestation_secret")

    monkeypatch.setattr(stripe, "create_customer", fake_create_customer)
    monkeypatch.setattr(stripe, "create_payment_intent", fake_create_payment_intent)

    operator_id = await create_user("attestation-operator@auracles.space", ["operator"])
    credential_id = await create_credential(operator_id)

    response = await client.post(
        "/v1/attestations",
        headers=auth_headers(operator_id, ["operator"]),
        json={
            "target_type": "credential",
            "target_id": str(credential_id),
            "requested_specializations": ["healthcare", "operations"],
            "requested_jurisdictions": ["US"],
        },
    )
    assert response.status_code == 201

    attestation_id = UUID(response.json()["id"])
    transaction_id = UUID(response.json()["transaction_id"])

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)
        transaction = await session.get(Transaction, transaction_id)
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "attestation_requested")
        )

    assert response.json()["provider"] == "stripe"
    assert response.json()["client_secret"] == "pi_attestation_secret"
    assert attestation is not None
    assert attestation.status == "pending_fee"
    assert attestation.target_type == "credential"
    assert attestation.target_id == credential_id
    assert attestation.requestor_id == operator_id
    assert attestation.requested_specializations == ["healthcare", "operations"]
    assert attestation.requested_jurisdictions == ["US"]
    assert transaction is not None
    assert transaction.transaction_type == "attestation_fee"
    assert transaction.status == "pending"
    assert transaction.provider == "stripe"
    assert transaction.provider_ref == "pi_attestation_123"
    assert transaction.payer_id == operator_id
    assert transaction.payee_id is None
    assert transaction.ref_id == attestation_id
    assert transaction.ref_type == "attestation"
    assert transaction.amount == Decimal("100.00")
    assert audit is not None
    assert stripe_calls["customers"] == [
        {
            "email": "attestation-operator@auracles.space",
            "name": "attestation-operator",
            "idempotency_key": f"stripe_customer:{operator_id}",
        }
    ]
    payment_intent = stripe_calls["payment_intents"][0]
    assert payment_intent["amount"] == Decimal("100.00")
    assert payment_intent["currency"] == "USD"
    assert payment_intent["idempotency_key"] == f"attestation_fee:{transaction_id}"
    metadata = payment_intent["metadata"]
    assert metadata["kind"] == "escrow"
    assert metadata["transaction_id"] == str(transaction_id)
    assert metadata["attestation_id"] == str(attestation_id)
    assert json.loads(metadata["release_conditions"]) == {
        "kind": "attestation",
        "attestation_id": str(attestation_id),
        "requestor_user_id": str(operator_id),
    }

    duplicate = await client.post(
        "/v1/attestations",
        headers=auth_headers(operator_id, ["operator"]),
        json={
            "target_type": "credential",
            "target_id": str(credential_id),
            "requested_specializations": ["healthcare"],
            "requested_jurisdictions": ["US"],
        },
    )
    assert duplicate.status_code == 409
