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
from app.integrations import stripe
from app.main import app
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestationUploadSession,
    AttestorApplication,
    AttestorProfile,
    Credential,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.modules.frameworks.models import Framework
from app.modules.webhooks.models import WebhookEvent
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for routes that do not use Redis directly."""


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
            await session.execute(delete(AttestorProfile))
            await session.execute(delete(AttestorApplication))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(Credential))
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

    monkeypatch.setattr(stripe, "create_customer", fake_create_customer)
    monkeypatch.setattr(stripe, "create_payment_intent", fake_create_payment_intent)


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
        assert await _attestation_fee(session, "contributor", None) == Decimal(
            "300.00"
        )
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


async def test_owner_notified_on_operator_initiated_funding(
    migrated_database: None,
    attestation_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Funding a non-owner framework request notifies the framework owner."""
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
            attestation_id = attestation.id

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
        call
        for call in notification_calls
        if call["notification_type"] == "attestation_requested_on_your_framework"
    ]
    assert owner_notifications == [
        {
            "user_id": str(owner_id),
            "notification_type": "attestation_requested_on_your_framework",
            "title": "Attestation requested on your framework",
            "body": (
                "Someone requested an independent attestation on your published "
                "framework."
            ),
            "payload": {
                "attestation_id": str(attestation_id),
                "target_type": "framework",
                "target_id": str(framework_id),
                "status": "matching",
            },
            "link": f"/attestations/{attestation_id}",
            "dedupe_key": (
                "attestation_requested_on_your_framework:"
                f"{attestation_id}:owner"
            ),
        }
    ]


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
