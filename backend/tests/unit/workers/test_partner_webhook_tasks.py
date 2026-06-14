"""Tests for Partner outbound webhook Celery delivery tasks."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.security import encrypt_partner_webhook_secret, hash_password
from app.modules.auth.models import User, UserRole
from app.modules.developer.models import (
    DeveloperAccount,
    DeveloperApplication,
    PartnerWebhook,
    PartnerWebhookDelivery,
)
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import partner_webhooks


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Developer webhook tables exist for worker tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def partner_webhook_context() -> Iterator[None]:
    """Reset Partner webhook rows before and after each worker test."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)

    def cleanup() -> None:
        """Delete rows in foreign-key-safe order."""
        with session_factory() as session:
            session.execute(delete(AuditLog))
            session.execute(delete(PartnerWebhookDelivery))
            session.execute(delete(PartnerWebhook))
            session.execute(delete(DeveloperAccount))
            session.execute(delete(DeveloperApplication))
            session.execute(delete(UserRole))
            session.execute(delete(User))
            session.commit()

    cleanup()
    try:
        yield
    finally:
        cleanup()
        sync_engine.dispose()


def create_pending_webhook_delivery(raw_secret: str, attempts: int = 0) -> UUID:
    """Create a pending outbound webhook delivery fixture."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    now = datetime.now(UTC)
    with session_factory() as session:
        user = User(
            email=f"webhook-worker-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Webhook Worker",
            email_verified=True,
        )
        session.add(user)
        session.flush()
        session.add(UserRole(user_id=user.id, role="developer", approved_at=now))
        application = DeveloperApplication(
            user_id=user.id,
            company_name="Webhook Worker Partner",
            website="https://worker-partner.example.com",
            use_case="Receive Auracles Partner webhook events.",
            status="approved",
            reviewed_at=now,
        )
        session.add(application)
        session.flush()
        account = DeveloperAccount(
            user_id=user.id,
            application_id=application.id,
            company_name=application.company_name,
            tier_rate=Decimal("0.0500"),
        )
        session.add(account)
        session.flush()
        webhook = PartnerWebhook(
            developer_account_id=account.id,
            url="https://partner.example.com/auracles/webhooks",
            secret_encrypted=encrypt_partner_webhook_secret(raw_secret),
            events=["purchase.confirmed"],
            active=True,
        )
        session.add(webhook)
        session.flush()
        delivery = PartnerWebhookDelivery(
            partner_webhook_id=webhook.id,
            event_type="purchase.confirmed",
            payload={
                "event": "purchase.confirmed",
                "transaction_id": str(uuid4()),
            },
            status="pending",
            attempts=attempts,
        )
        session.add(delivery)
        session.flush()
        delivery_id = delivery.id
        session.commit()
    sync_engine.dispose()
    return delivery_id


def test_deliver_partner_webhook_signs_payload_and_marks_delivered(
    migrated_database: None,
    partner_webhook_context: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful webhook delivery sends HMAC headers and becomes delivered."""
    del migrated_database, partner_webhook_context
    raw_secret = "whsec_test_delivery_secret"
    delivery_id = create_pending_webhook_delivery(raw_secret)
    captured: dict[str, object] = {}

    async def fake_post_webhook(
        url: str,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> int:
        """Capture the outbound request without making a network call."""
        captured["url"] = url
        captured["raw_body"] = raw_body
        captured["headers"] = headers
        return 204

    monkeypatch.setattr(partner_webhooks, "_post_webhook", fake_post_webhook)

    result = partner_webhooks.deliver_partner_webhook.apply(
        args=[str(delivery_id)]
    ).get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        delivery = session.get(PartnerWebhookDelivery, delivery_id)
        audit_count = (
            session.query(AuditLog)
            .filter_by(action="partner_webhook_delivered")
            .count()
        )
    sync_engine.dispose()

    headers = captured["headers"]
    raw_body = captured["raw_body"]
    assert result == {"delivery_id": str(delivery_id), "status": "delivered"}
    assert captured["url"] == "https://partner.example.com/auracles/webhooks"
    assert isinstance(headers, dict)
    assert isinstance(raw_body, bytes)
    assert headers["X-Auracles-Event"] == "purchase.confirmed"
    expected_signature = hmac.new(
        raw_secret.encode("utf-8"),
        f"{headers['X-Auracles-Timestamp']}.".encode() + raw_body,
        hashlib.sha256,
    ).hexdigest()
    assert headers["X-Auracles-Signature"] == expected_signature
    assert json.loads(raw_body.decode("utf-8"))["event"] == "purchase.confirmed"
    assert delivery is not None
    assert delivery.status == "delivered"
    assert delivery.attempts == 1
    assert delivery.response_code == 204
    assert delivery.next_attempt_at is None
    assert audit_count == 1


def test_deliver_partner_webhook_dead_letters_after_fifth_failure(
    migrated_database: None,
    partner_webhook_context: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fifth failed webhook attempt becomes dead and stops retrying."""
    del migrated_database, partner_webhook_context
    delivery_id = create_pending_webhook_delivery("whsec_failure_secret", attempts=4)

    async def fake_post_webhook(
        url: str,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> int:
        """Return a non-2xx response without making a network call."""
        del url, raw_body, headers
        return 500

    monkeypatch.setattr(partner_webhooks, "_post_webhook", fake_post_webhook)

    result = partner_webhooks.deliver_partner_webhook.apply(
        args=[str(delivery_id)]
    ).get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        delivery = session.get(PartnerWebhookDelivery, delivery_id)
        audit_count = (
            session.query(AuditLog).filter_by(action="partner_webhook_dead").count()
        )
    sync_engine.dispose()

    assert result == {"delivery_id": str(delivery_id), "status": "dead"}
    assert delivery is not None
    assert delivery.status == "dead"
    assert delivery.attempts == 5
    assert delivery.response_code == 500
    assert delivery.next_attempt_at is None
    assert audit_count == 1


def _public_getaddrinfo(*_args: object, **_kwargs: object) -> list[tuple]:
    """Resolve any host to a public address for SSRF-guard tests."""
    return [(2, 1, 6, "", ("8.8.8.8", 443))]


def _private_getaddrinfo(*_args: object, **_kwargs: object) -> list[tuple]:
    """Resolve any host to an internal address for SSRF-guard tests."""
    return [(2, 1, 6, "", ("10.0.0.5", 443))]


def _update_delivery(
    delivery_id: UUID,
    *,
    status: str | None = None,
    webhook_active: bool | None = None,
    next_attempt_at: datetime | None = None,
) -> None:
    """Mutate a delivery and/or its webhook for edge-case coverage."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        delivery = session.get(PartnerWebhookDelivery, delivery_id)
        assert delivery is not None
        if status is not None:
            delivery.status = status
        if next_attempt_at is not None:
            delivery.next_attempt_at = next_attempt_at
        if webhook_active is not None:
            webhook = session.get(PartnerWebhook, delivery.partner_webhook_id)
            assert webhook is not None
            webhook.active = webhook_active
        session.commit()
    sync_engine.dispose()


def test_is_blocked_ip_flags_internal_addresses() -> None:
    """Private, loopback, link-local, multicast, and unspecified IPs are blocked."""
    for blocked in ("127.0.0.1", "10.0.0.1", "169.254.0.1", "224.0.0.1", "0.0.0.0"):
        assert partner_webhooks._is_blocked_ip(blocked) is True
    assert partner_webhooks._is_blocked_ip("8.8.8.8") is False


def test_next_retry_at_grows_and_caps_at_one_hour() -> None:
    """Backoff doubles with attempts and is capped at one hour."""
    base = datetime.now(UTC)
    first = partner_webhooks._next_retry_at(1)
    later = partner_webhooks._next_retry_at(3)
    capped = partner_webhooks._next_retry_at(20)

    assert (later - first).total_seconds() > 0
    assert (capped - base).total_seconds() <= 3600 + 5


def test_validate_webhook_url_rejects_non_https() -> None:
    """A non-HTTPS webhook destination is refused before any network call."""
    with pytest.raises(ValueError, match="HTTPS"):
        partner_webhooks._validate_webhook_url_for_delivery(
            "http://partner.example.com"
        )


def test_validate_webhook_url_rejects_internal_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A webhook host resolving to an internal address is blocked (SSRF guard)."""
    monkeypatch.setattr(partner_webhooks.socket, "getaddrinfo", _private_getaddrinfo)
    with pytest.raises(ValueError, match="blocked address"):
        partner_webhooks._validate_webhook_url_for_delivery(
            "https://internal.example.com/hook"
        )


def test_validate_webhook_url_allows_public_https(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A public HTTPS destination passes the SSRF guard."""
    monkeypatch.setattr(partner_webhooks.socket, "getaddrinfo", _public_getaddrinfo)
    partner_webhooks._validate_webhook_url_for_delivery("https://partner.example.com/h")


def test_deliver_skips_already_delivered_delivery(
    migrated_database: None,
    partner_webhook_context: None,
) -> None:
    """A delivery already marked delivered is a no-op that returns its status."""
    del migrated_database, partner_webhook_context
    delivery_id = create_pending_webhook_delivery("whsec_done_secret")
    _update_delivery(delivery_id, status="delivered")

    result = partner_webhooks.deliver_partner_webhook.apply(
        args=[str(delivery_id)]
    ).get()

    assert result == {"delivery_id": str(delivery_id), "status": "delivered"}


def test_deliver_dead_letters_inactive_webhook(
    migrated_database: None,
    partner_webhook_context: None,
) -> None:
    """A delivery for a deactivated webhook is dead-lettered without sending."""
    del migrated_database, partner_webhook_context
    delivery_id = create_pending_webhook_delivery("whsec_inactive_secret")
    _update_delivery(delivery_id, webhook_active=False)

    result = partner_webhooks.deliver_partner_webhook.apply(
        args=[str(delivery_id)]
    ).get()

    assert result == {"delivery_id": str(delivery_id), "status": "dead"}


def test_retry_due_partner_webhooks_queues_due_failed_deliveries(
    migrated_database: None,
    partner_webhook_context: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry sweep re-queues only failed deliveries whose backoff has elapsed."""
    del migrated_database, partner_webhook_context
    delivery_id = create_pending_webhook_delivery("whsec_retry_secret", attempts=1)
    _update_delivery(
        delivery_id,
        status="failed",
        next_attempt_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    queued: list[str] = []
    monkeypatch.setattr(
        partner_webhooks.deliver_partner_webhook,
        "delay",
        lambda value: queued.append(value),
    )

    result = partner_webhooks.retry_due_partner_webhooks.apply().get()

    assert result == {"queued_count": 1}
    assert queued == [str(delivery_id)]
