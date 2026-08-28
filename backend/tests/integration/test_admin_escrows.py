"""Integration tests for admin escrow override endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials import escrow_service
from app.modules.financials.models import Escrow, Transaction
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async


class FakeRedis:
    """Redis test double for TOTP-sensitive admin routes."""

    def __init__(self) -> None:
        """Create empty in-memory Redis state."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored value or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def incr(self, key: str) -> int:
        """Increment and return a counter."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """Record a TTL for a key."""
        self.ttls[key] = seconds

    async def delete(self, *keys: str) -> int:
        """Delete stored values and counters."""
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.counters)
            self.values.pop(key, None)
            self.counters.pop(key, None)
            self.ttls.pop(key, None)
        return removed


class FakeStripeRefund:
    """Small stand-in for a Stripe refund result."""

    def __init__(self, refund_id: str) -> None:
        """Store the provider refund id and status."""
        self.id = refund_id
        self.status = "succeeded"


async def reset_admin_escrow_state() -> None:
    """Remove admin escrow test data in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(Escrow))
        await session.execute(delete(Transaction))
        await clear_identity_state_async(session)
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure financial tables exist for admin escrow tests."""
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
async def admin_escrow_context() -> AsyncIterator[dict[str, Any]]:
    """Reset auth/financial state and install Redis test double."""
    fake_redis = FakeRedis()
    refund_calls: list[dict[str, Any]] = []
    await engine.dispose()
    await reset_admin_escrow_state()

    async def override_redis() -> FakeRedis:
        """Return the Redis test double for dependency injection."""
        return fake_redis

    async def fake_create_refund(
        *,
        payment_intent_id: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> FakeStripeRefund:
        """Record provider refund requests for admin escrow tests."""
        refund_calls.append(
            {
                "payment_intent_id": payment_intent_id,
                "amount": amount,
                "currency": currency,
                "idempotency_key": idempotency_key,
            }
        )
        return FakeStripeRefund("re_admin_escrow_123")

    app.dependency_overrides[get_redis] = override_redis
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(escrow_service.stripe, "create_refund", fake_create_refund)
    try:
        yield {"redis": fake_redis, "refund_calls": refund_calls}
    finally:
        monkeypatch.undo()
        app.dependency_overrides.pop(get_redis, None)
        await reset_admin_escrow_state()
        await engine.dispose()


async def create_admin_user(*, enable_totp: bool = True) -> tuple[UUID, str | None]:
    """Create an admin user and optional encrypted TOTP secret."""
    secret = pyotp.random_base32() if enable_totp else None
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"admin-{uuid4()}@auracles.space",
                password_hash="not-used",
                display_name="Admin",
                email_verified=True,
                totp_enabled=enable_totp,
                totp_secret=encrypt_totp_secret(secret) if secret else None,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(
                    user_id=user.id,
                    role="admin",
                    approved_at=datetime.now(UTC),
                )
            )
        return user.id, secret


async def create_held_escrow() -> UUID:
    """Create a held project milestone escrow with a completed transaction."""
    operator_id = await create_admin_user(enable_totp=False)
    payee_id = await create_admin_user(enable_totp=False)
    milestone_id = uuid4()
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_id=operator_id[0],
                payee_id=payee_id[0],
                amount=Decimal("500.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("500.00"),
                transaction_type="milestone",
                status="completed",
                provider="stripe",
                provider_ref=f"pi_admin_escrow_{uuid4()}",
                ref_id=milestone_id,
                ref_type="project_milestone",
            )
            session.add(transaction)
            await session.flush()
            escrow = Escrow(
                ref_id=milestone_id,
                ref_type="project_milestone",
                amount=Decimal("500.00"),
                currency="USD",
                status="held",
                release_conditions={"required_event": "operator_approval"},
                transaction_id=transaction.id,
            )
            session.add(escrow)
            await session.flush()
            return escrow.id


def auth_headers(user_id: UUID) -> dict[str, str]:
    """Create admin bearer auth headers for tests."""
    token = create_access_token(user_id=user_id, roles=["admin"])
    return {"Authorization": f"Bearer {token}"}


async def test_admin_releases_held_escrow_with_totp_reason_and_idempotency(
    client: AsyncClient,
    migrated_database: None,
    admin_escrow_context: dict[str, Any],
) -> None:
    """Admin override can release held escrow once and records the reason."""
    del migrated_database, admin_escrow_context
    admin_id, totp_secret = await create_admin_user()
    escrow_id = await create_held_escrow()
    assert totp_secret is not None
    code = pyotp.TOTP(totp_secret).now()

    first = await client.post(
        f"/v1/admin/escrows/{escrow_id}/release",
        headers=auth_headers(admin_id),
        json={
            "reason": "Operator approval confirmed by support.",
            "totp_code": code,
        },
    )
    second = await client.post(
        f"/v1/admin/escrows/{escrow_id}/release",
        headers=auth_headers(admin_id),
        json={"reason": "Repeated support action.", "totp_code": code},
    )

    async with async_session_factory() as session:
        escrow = await session.get(Escrow, escrow_id)
        audits = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "escrow_released")
                )
            )
            .scalars()
            .all()
        )

    assert first.status_code == 200
    assert first.json()["status"] == "released"
    assert first.json()["released_by"] == str(admin_id)
    assert second.status_code == 200
    assert second.json()["status"] == "released"
    assert escrow is not None
    assert escrow.status == "released"
    assert escrow.released_by == admin_id
    assert len(audits) == 1
    assert audits[0].metadata_["reason"] == "Operator approval confirmed by support."
    assert audits[0].metadata_["admin_override"] is True


async def test_admin_refunds_held_escrow_and_totp_is_required(
    client: AsyncClient,
    migrated_database: None,
    admin_escrow_context: dict[str, Any],
) -> None:
    """Admin override refunds held escrow only after TOTP confirmation."""
    del migrated_database
    admin_id, totp_secret = await create_admin_user()
    escrow_id = await create_held_escrow()
    assert totp_secret is not None

    missing_totp = await client.post(
        f"/v1/admin/escrows/{escrow_id}/refund",
        headers=auth_headers(admin_id),
        json={
            "reason": "Dispute resolved in Operator favor.",
            "totp_code": "000000",
        },
    )
    code = pyotp.TOTP(totp_secret).now()
    refunded = await client.post(
        f"/v1/admin/escrows/{escrow_id}/refund",
        headers=auth_headers(admin_id),
        json={"reason": "Dispute resolved in Operator favor.", "totp_code": code},
    )

    async with async_session_factory() as session:
        escrow = await session.get(Escrow, escrow_id)
        transaction = (
            await session.get(Transaction, escrow.transaction_id)
            if escrow is not None
            else None
        )
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "escrow_refunded")
        )

    assert missing_totp.status_code == 422
    assert refunded.status_code == 200
    assert refunded.json()["status"] == "refunded"
    assert escrow is not None
    assert escrow.status == "refunded"
    assert transaction is not None
    assert transaction.status == "refunded"
    assert admin_escrow_context["refund_calls"] == [
        {
            "payment_intent_id": transaction.provider_ref,
            "amount": Decimal("500.00"),
            "currency": "USD",
            "idempotency_key": f"escrow_refund:{escrow_id}",
        }
    ]
    assert audit is not None
    assert audit.metadata_["reason"] == "Dispute resolved in Operator favor."
