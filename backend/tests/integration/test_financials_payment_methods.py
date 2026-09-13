"""Integration tests for Operator payment method management."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    encrypt_totp_secret,
    hash_password,
)
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials import service as financials_service
from app.shared.models.audit_log import AuditLog
from tests.conftest import open_step_up_window


class FakeRedis:
    """Redis test double for TOTP-sensitive financial routes."""

    async def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool:
        """Store a string value, optionally respecting NX semantics."""
        del ex
        store = self.__dict__.setdefault("values", {})
        if nx and key in store:
            return False
        store[key] = value
        return True

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a string value with a TTL (test double ignores expiry)."""
        del seconds
        self.__dict__.setdefault("values", {})[key] = value

    def __init__(self) -> None:
        """Create empty in-memory counter and value storage."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored string or counter value."""
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


class FakeStripeCustomer:
    """Small stand-in for a Stripe customer result."""

    def __init__(self, customer_id: str) -> None:
        """Store the provider customer id."""
        self.id = customer_id


class FakeStripeSetupIntent:
    """Small stand-in for a Stripe SetupIntent result."""

    def __init__(self, setup_intent_id: str, client_secret: str) -> None:
        """Store the provider SetupIntent fields returned to the client."""
        self.id = setup_intent_id
        self.client_secret = client_secret


class FakeStripePaymentMethod:
    """Small stand-in for safe Stripe payment method metadata."""

    def __init__(self, payment_method_id: str) -> None:
        """Store safe card metadata without PAN data."""
        self.id = payment_method_id
        self.type = "card"
        self.brand = "visa"
        self.last4 = "4242"
        self.exp_month = 8
        self.exp_year = 2028


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure financial tables exist for payment method tests."""
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
async def payment_method_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset auth/audit state and replace Stripe calls with test doubles."""
    fake_redis = FakeRedis()
    calls: dict[str, list[Any]] = {
        "customers": [],
        "setup_intents": [],
        "list_methods": [],
        "detached": [],
    }

    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()

    async def fake_create_customer(
        *,
        email: str,
        name: str | None = None,
        idempotency_key: str | None = None,
    ) -> FakeStripeCustomer:
        """Record customer creation and return a stable provider id."""
        calls["customers"].append(
            {"email": email, "name": name, "idempotency_key": idempotency_key}
        )
        return FakeStripeCustomer("cus_test_123")

    async def fake_create_setup_intent(
        *,
        customer_id: str,
    ) -> FakeStripeSetupIntent:
        """Record SetupIntent creation and return a client secret."""
        calls["setup_intents"].append(customer_id)
        return FakeStripeSetupIntent("seti_test_123", "seti_secret_123")

    async def fake_list_payment_methods(
        *,
        customer_id: str,
    ) -> list[FakeStripePaymentMethod]:
        """Record list calls and return one provider-held card."""
        calls["list_methods"].append(customer_id)
        return [FakeStripePaymentMethod("pm_test_123")]

    async def fake_detach_payment_method(
        *,
        payment_method_id: str,
    ) -> str:
        """Record detach calls and return the removed provider id."""
        calls["detached"].append(payment_method_id)
        return payment_method_id

    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr(
        financials_service.stripe,
        "create_customer",
        fake_create_customer,
    )
    monkeypatch.setattr(
        financials_service.stripe,
        "create_setup_intent",
        fake_create_setup_intent,
    )
    monkeypatch.setattr(
        financials_service.stripe,
        "list_payment_methods",
        fake_list_payment_methods,
    )
    monkeypatch.setattr(
        financials_service.stripe,
        "detach_payment_method",
        fake_detach_payment_method,
    )
    try:
        yield {"redis": fake_redis, "calls": calls}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await engine.dispose()


async def create_user_with_roles(
    email: str,
    roles: list[str],
    *,
    enable_totp: bool = True,
    kyc_status: str = "verified",
) -> tuple[UUID, str | None]:
    """Create a verified user with approved roles, optional TOTP, and KYC status."""
    secret = pyotp.random_base32() if enable_totp else None
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status=kyc_status,
                totp_enabled=enable_totp,
                totp_secret=encrypt_totp_secret(secret) if secret else None,
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
        return user.id, secret


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_operator_can_start_stripe_payment_method_setup(
    client: AsyncClient,
    migrated_database: None,
    payment_method_context: dict[str, Any],
) -> None:
    """Operator receives a SetupIntent secret and only provider ids are stored."""
    user_id, _ = await create_user_with_roles(
        "payment-operator@auracles.space",
        ["operator"],
    )
    await open_step_up_window(payment_method_context["redis"], user_id)

    response = await client.post(
        "/v1/financials/payment-methods",
        headers=auth_headers(user_id, ["operator"]),
    )

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "payment_method_added")
        )

    calls = payment_method_context["calls"]
    assert response.status_code == 200
    assert response.json() == {
        "provider": "stripe",
        "setup_intent_id": "seti_test_123",
        "client_secret": "seti_secret_123",
    }
    assert user is not None
    assert user.stripe_customer_id == "cus_test_123"
    assert calls["customers"] == [
        {
            "email": "payment-operator@auracles.space",
            "name": "payment-operator",
            "idempotency_key": f"stripe_customer:{user_id}",
        }
    ]
    assert calls["setup_intents"] == ["cus_test_123"]
    assert audit is not None
    assert audit.actor_id == user_id
    assert audit.metadata_["provider"] == "stripe"


async def test_unverified_operator_cannot_set_up_payment_method(
    client: AsyncClient,
    migrated_database: None,
    payment_method_context: dict[str, Any],
) -> None:
    """Adding a payment method requires verified KYC; unverified is blocked (403)."""
    user_id, _ = await create_user_with_roles(
        "kyc-gate-payment@auracles.space",
        ["operator"],
        kyc_status="unverified",
    )
    await open_step_up_window(payment_method_context["redis"], user_id)

    response = await client.post(
        "/v1/financials/payment-methods",
        headers=auth_headers(user_id, ["operator"]),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "kyc_required"


async def test_operator_lists_and_removes_provider_held_payment_methods(
    client: AsyncClient,
    migrated_database: None,
    payment_method_context: dict[str, Any],
) -> None:
    """List/delete proxy safe card metadata and never expose full card numbers."""
    user_id, _ = await create_user_with_roles(
        "payment-list@auracles.space",
        ["operator"],
    )
    await open_step_up_window(payment_method_context["redis"], user_id)
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.stripe_customer_id = "cus_existing_123"
        await session.commit()

    listed = await client.get(
        "/v1/financials/payment-methods",
        headers=auth_headers(user_id, ["operator"]),
    )
    removed = await client.request(
        "DELETE",
        "/v1/financials/payment-methods/pm_test_123",
        headers=auth_headers(user_id, ["operator"]),
    )

    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "payment_method_removed")
        )

    assert listed.status_code == 200
    assert listed.json() == {
        "payment_methods": [
            {
                "id": "pm_test_123",
                "provider": "stripe",
                "type": "card",
                "brand": "visa",
                "last4": "4242",
                "exp_month": 8,
                "exp_year": 2028,
            }
        ]
    }
    assert "4242424242424242" not in listed.text
    assert removed.status_code == 200
    assert removed.json() == {
        "provider": "stripe",
        "payment_method_id": "pm_test_123",
        "removed": True,
    }
    assert payment_method_context["calls"]["list_methods"] == [
        "cus_existing_123",
        "cus_existing_123",
    ]
    assert payment_method_context["calls"]["detached"] == ["pm_test_123"]
    assert audit is not None
    assert audit.metadata_["payment_method_ref"] == "****_123"


async def test_payment_method_changes_require_open_step_up_window(
    client: AsyncClient,
    migrated_database: None,
    payment_method_context: dict[str, Any],
) -> None:
    """Without an open step-up window, setup and removal answer 403.

    Nothing reaches Stripe: no customer or SetupIntent is created and no
    method is detached.
    """
    del migrated_database
    user_id, _ = await create_user_with_roles(
        "payment-no-window@auracles.space",
        ["operator"],
    )

    setup = await client.post(
        "/v1/financials/payment-methods",
        headers=auth_headers(user_id, ["operator"]),
    )
    removed = await client.request(
        "DELETE",
        "/v1/financials/payment-methods/pm_test_123",
        headers=auth_headers(user_id, ["operator"]),
    )

    calls = payment_method_context["calls"]
    assert setup.status_code == 403
    assert setup.json()["detail"]["error_code"] == "step_up_required"
    assert removed.status_code == 403
    assert removed.json()["detail"]["error_code"] == "step_up_required"
    assert calls["customers"] == []
    assert calls["setup_intents"] == []
    assert calls["detached"] == []


async def test_payment_method_changes_require_operator_role_and_totp(
    client: AsyncClient,
    migrated_database: None,
    payment_method_context: dict[str, Any],
) -> None:
    """Payment method writes are RBAC-gated, need enrolled 2FA, and reject PANs."""
    contributor_id, _ = await create_user_with_roles(
        "payment-contributor@auracles.space",
        ["contributor"],
    )
    operator_id, _ = await create_user_with_roles(
        "payment-no-2fa@auracles.space",
        ["operator"],
        enable_totp=False,
    )
    enrolled_operator_id, _ = await create_user_with_roles(
        "payment-enrolled@auracles.space",
        ["operator"],
    )
    await open_step_up_window(payment_method_context["redis"], contributor_id)
    await open_step_up_window(payment_method_context["redis"], enrolled_operator_id)

    wrong_role = await client.post(
        "/v1/financials/payment-methods",
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    no_totp = await client.post(
        "/v1/financials/payment-methods",
        headers=auth_headers(operator_id, ["operator"]),
    )
    invalid_pan_shape = await client.post(
        "/v1/financials/payment-methods",
        headers=auth_headers(enrolled_operator_id, ["operator"]),
        json={"card_number": "4242424242424242"},
    )

    assert wrong_role.status_code == 403
    assert no_totp.status_code == 403
    assert no_totp.json()["detail"]["error_code"] == "totp_setup_required"
    assert invalid_pan_shape.status_code == 422
