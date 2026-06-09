"""Integration tests for Stripe webhook ingestion and dispatch."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.integrations.stripe import StripeProviderError
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework, License
from app.modules.webhooks import service as webhook_service
from app.modules.webhooks.models import WebhookEvent
from app.shared.models.audit_log import AuditLog


async def reset_webhook_state() -> None:
    """Remove webhook test data in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(WebhookEvent))
        await session.execute(delete(AuditLog))
        await session.execute(delete(License))
        await session.execute(delete(Transaction))
        await session.execute(delete(Framework))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture
async def webhook_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset state and install a controllable Stripe verifier double."""
    await engine.dispose()
    await reset_webhook_state()
    context: dict[str, Any] = {"event": None, "verified_payloads": []}

    def fake_verify_webhook(
        payload: bytes,
        signature_header: str | None,
    ) -> dict[str, Any]:
        """Record raw body verification and return the configured event."""
        context["verified_payloads"].append(
            {"payload": payload, "signature": signature_header}
        )
        if signature_header == "bad-signature":
            raise StripeProviderError("bad signature")
        event = context["event"]
        if not isinstance(event, dict):
            raise StripeProviderError("missing test event")
        return event

    monkeypatch.setattr(
        webhook_service.stripe,
        "verify_webhook",
        fake_verify_webhook,
    )
    try:
        yield context
    finally:
        await reset_webhook_state()
        await engine.dispose()


async def create_user_with_roles(email: str, roles: list[str]) -> UUID:
    """Create a verified user with approved roles."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash="not-used",
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


async def create_pending_purchase() -> tuple[UUID, UUID, UUID, UUID]:
    """Create a pending purchase transaction that a webhook can complete."""
    contributor_id = await create_user_with_roles(
        "webhook-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "webhook-operator@auracles.space",
        ["operator"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title="Webhook Purchase Framework",
                description="Framework used by Stripe webhook tests.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["stripe", "webhook"],
                price=Decimal("149.00"),
                currency="USD",
                license_types=["single_user", "team", "organizational"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=Decimal("149.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("149.00"),
                transaction_type="purchase",
                status="pending",
                provider="stripe",
                provider_ref="pi_webhook_123",
                ref_id=framework.id,
                ref_type="framework",
            )
            session.add(transaction)
            await session.flush()
            return transaction.id, framework.id, operator_id, contributor_id


def payment_intent_event(
    event_id: str,
    event_type: str,
    *,
    transaction_id: UUID,
    framework_id: UUID,
    license_type: str = "team",
) -> dict[str, Any]:
    """Build a Stripe PaymentIntent event payload for purchase tests."""
    return {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": "pi_webhook_123",
                "metadata": {
                    "transaction_id": str(transaction_id),
                    "kind": "purchase",
                    "framework_id": str(framework_id),
                    "license_type": license_type,
                },
            }
        },
    }


async def test_stripe_payment_intent_success_creates_license_once(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A verified purchase webhook completes the transaction and grants access."""
    transaction_id, framework_id, operator_id, _ = await create_pending_purchase()
    webhook_context["event"] = payment_intent_event(
        "evt_purchase_success",
        "payment_intent.succeeded",
        transaction_id=transaction_id,
        framework_id=framework_id,
    )

    first = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )
    replay = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        licenses = (
            await session.execute(
                select(License).where(License.framework_id == framework_id)
            )
        ).scalars().all()
        events = (await session.execute(select(WebhookEvent))).scalars().all()
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "purchase_completed")
        )

    assert first.status_code == 200
    assert first.json() == {"received": True, "status": "processed"}
    assert replay.status_code == 200
    assert replay.json() == {"received": True, "status": "duplicate"}
    assert transaction is not None
    assert transaction.status == "completed"
    assert len(licenses) == 1
    assert licenses[0].operator_id == operator_id
    assert licenses[0].transaction_id == transaction_id
    assert licenses[0].license_type == "team"
    assert licenses[0].seats_total == 10
    assert len(events) == 1
    assert events[0].provider_event_id == "evt_purchase_success"
    assert events[0].status == "processed"
    assert audit is not None
    assert audit.target_id == transaction_id


async def test_stripe_webhook_rejects_bad_signature_before_event_storage(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """Invalid signatures return 400 and do not create webhook event rows."""
    webhook_context["event"] = {"id": "evt_bad", "type": "payment_intent.succeeded"}

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "bad-signature"},
    )

    async with async_session_factory() as session:
        event = await session.scalar(select(WebhookEvent))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "webhook_signature_invalid")
        )

    assert response.status_code == 400
    assert event is None
    assert audit is not None
    assert audit.metadata_["provider"] == "stripe"


async def test_stripe_payment_intent_failure_marks_purchase_failed(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A verified payment failure webhook marks the local purchase failed."""
    transaction_id, framework_id, _, _ = await create_pending_purchase()
    webhook_context["event"] = payment_intent_event(
        "evt_purchase_failed",
        "payment_intent.payment_failed",
        transaction_id=transaction_id,
        framework_id=framework_id,
    )

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        license_row = await session.scalar(select(License))
        event = await session.scalar(
            select(WebhookEvent).where(
                WebhookEvent.provider_event_id == "evt_purchase_failed"
            )
        )
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "purchase_failed")
        )

    assert response.status_code == 200
    assert response.json() == {"received": True, "status": "processed"}
    assert transaction is not None
    assert transaction.status == "failed"
    assert license_row is None
    assert event is not None
    assert event.status == "processed"
    assert audit is not None
    assert audit.target_id == transaction_id
