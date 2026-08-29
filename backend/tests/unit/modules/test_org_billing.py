"""Unit tests for organization payment-method billing services."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_factory, engine
from app.core.security import encrypt_totp_secret, hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.financials.models import Transaction
from app.modules.organizations.models import Organization, OrgMember
from tests.integration.test_financials_payment_methods import FakeRedis
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


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
    """Ensure the current schema exists for org-billing unit tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        command.upgrade(alembic_config, "head")
        sync_engine.dispose()


@pytest.fixture
async def org_billing_state() -> AsyncIterator[dict[str, Any]]:
    """Reset org-billing rows around each unit test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete billing-related rows in a foreign-key-safe order."""
        async with async_session_factory() as session:
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    try:
        yield {"redis": FakeRedis()}
    finally:
        await cleanup()
        await engine.dispose()


async def _create_user(prefix: str, *, enable_totp: bool = True) -> tuple[User, str]:
    """Create one verified user and return it with its plaintext TOTP secret."""
    secret = pyotp.random_base32()
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status="verified",
                totp_enabled=enable_totp,
                totp_secret=encrypt_totp_secret(secret),
            )
            session.add(user)
            await session.flush()
            await session.refresh(user)
            return user, secret


async def _create_org(owner: User) -> Organization:
    """Create one organization with the given owner as an org owner member."""
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"org-{uuid4().hex[:6]}",
                name="Org Billing Test Org",
                country="US",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            await session.refresh(org)
            return org


@pytest.mark.asyncio
async def test_create_org_payment_method_setup_creates_customer_once_and_reuses_it(
    migrated_database: None,
    org_billing_state: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Org SetupIntent creation lazily persists one Stripe customer and reuses it."""
    del migrated_database
    import app.modules.organizations.billing_service as billing_service

    owner, totp_secret = await _create_user("org-billing-owner")
    org = await _create_org(owner)
    calls: dict[str, list[Any]] = {"customers": [], "setup_intents": []}

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
        return FakeStripeCustomer("cus_org_test_123")

    async def fake_create_setup_intent(
        *,
        customer_id: str,
    ) -> FakeStripeSetupIntent:
        """Record SetupIntent creation and return a client secret."""
        calls["setup_intents"].append(customer_id)
        return FakeStripeSetupIntent("seti_org_123", "seti_org_secret_123")

    monkeypatch.setattr(billing_service.stripe, "create_customer", fake_create_customer)
    monkeypatch.setattr(
        billing_service.stripe,
        "create_setup_intent",
        fake_create_setup_intent,
    )

    first_code = pyotp.TOTP(totp_secret).now()
    async with async_session_factory() as session:
        first = await billing_service.create_org_payment_method_setup(
            session,
            org_billing_state["redis"],
            org_id=org.id,
            actor=owner,
            totp_code=first_code,
        )

    async with async_session_factory() as session:
        stored_org = await session.get(Organization, org.id)
    assert stored_org is not None
    assert stored_org.stripe_customer_id == "cus_org_test_123"
    assert first.setup_intent_id == "seti_org_123"

    # A fresh code from the next time step: the first setup consumed the
    # current one, and TOTP codes are single-use now (M4).
    second_code = pyotp.TOTP(totp_secret).at(
        datetime.now(UTC) + timedelta(seconds=30)
    )
    async with async_session_factory() as session:
        second = await billing_service.create_org_payment_method_setup(
            session,
            org_billing_state["redis"],
            org_id=org.id,
            actor=owner,
            totp_code=second_code,
        )

    assert second.client_secret == "seti_org_secret_123"
    assert calls["customers"] == [
        {
            "email": owner.email,
            "name": "Org Billing Test Org",
            "idempotency_key": f"stripe_customer:org:{org.id}",
        }
    ]
    assert calls["setup_intents"] == ["cus_org_test_123", "cus_org_test_123"]


@pytest.mark.asyncio
async def test_list_org_payment_methods_returns_only_safe_card_metadata(
    migrated_database: None,
    org_billing_state: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Org payment-method listing returns masked card metadata only."""
    del migrated_database, org_billing_state
    import app.modules.organizations.billing_service as billing_service

    owner, _totp_secret = await _create_user("org-billing-owner")
    org = await _create_org(owner)
    async with async_session_factory() as session:
        async with session.begin():
            stored_org = await session.get(Organization, org.id)
            assert stored_org is not None
            stored_org.stripe_customer_id = "cus_org_existing_123"

    async def fake_list_payment_methods(
        *,
        customer_id: str,
    ) -> list[FakeStripePaymentMethod]:
        """Return one provider-held card for the org customer."""
        assert customer_id == "cus_org_existing_123"
        return [FakeStripePaymentMethod("pm_org_test_123")]

    monkeypatch.setattr(
        billing_service.stripe,
        "list_payment_methods",
        fake_list_payment_methods,
    )

    async with async_session_factory() as session:
        response = await billing_service.list_org_payment_methods(
            session,
            org_id=org.id,
        )

    assert response.model_dump() == {
        "payment_methods": [
            {
                "id": "pm_org_test_123",
                "provider": "stripe",
                "type": "card",
                "brand": "visa",
                "last4": "4242",
                "exp_month": 8,
                "exp_year": 2028,
            }
        ]
    }
    assert "4242424242424242" not in response.model_dump_json()


@pytest.mark.asyncio
async def test_delete_org_payment_method_rejects_method_not_owned_by_org_customer(
    migrated_database: None,
    org_billing_state: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Org payment-method deletion must 404 for a non-owned method."""
    del migrated_database
    import app.modules.organizations.billing_service as billing_service

    owner, totp_secret = await _create_user("org-billing-owner")
    org = await _create_org(owner)
    async with async_session_factory() as session:
        async with session.begin():
            stored_org = await session.get(Organization, org.id)
            assert stored_org is not None
            stored_org.stripe_customer_id = "cus_org_existing_123"

    async def fake_list_payment_methods(
        *,
        customer_id: str,
    ) -> list[FakeStripePaymentMethod]:
        """Return one provider-held card that does not match the requested id."""
        assert customer_id == "cus_org_existing_123"
        return [FakeStripePaymentMethod("pm_other_customer_card")]

    detached: list[str] = []

    async def fake_detach_payment_method(*, payment_method_id: str) -> str:
        """Record detach attempts so the test can assert none happen."""
        detached.append(payment_method_id)
        return payment_method_id

    monkeypatch.setattr(
        billing_service.stripe,
        "list_payment_methods",
        fake_list_payment_methods,
    )
    monkeypatch.setattr(
        billing_service.stripe,
        "detach_payment_method",
        fake_detach_payment_method,
    )

    with pytest.raises(HTTPException) as exc_info:
        async with async_session_factory() as session:
            await billing_service.delete_org_payment_method(
                session,
                org_billing_state["redis"],
                org_id=org.id,
                actor=owner,
                payment_method_id="pm_org_missing_123",
                totp_code=pyotp.TOTP(totp_secret).now(),
            )

    assert exc_info.value.status_code == 404
    assert detached == []


@pytest.mark.asyncio
async def test_transaction_payer_xor_rejects_neither_and_both_payer_shapes(
    migrated_database: None,
    org_billing_state: dict[str, Any],
) -> None:
    """Transactions must resolve to exactly one payer: user or organization."""
    del migrated_database, org_billing_state

    owner, _totp_secret = await _create_user("org-billing-owner")
    org = await _create_org(owner)

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    Transaction(
                        payer_id=None,
                        payer_org_id=None,
                        payee_id=owner.id,
                        payee_org_id=None,
                        amount=Decimal("10.00"),
                        currency="USD",
                        platform_commission=Decimal("0.00"),
                        net_amount=Decimal("10.00"),
                        transaction_type="purchase",
                        status="pending",
                    )
                )
                await session.flush()

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    Transaction(
                        payer_id=owner.id,
                        payer_org_id=org.id,
                        payee_id=owner.id,
                        payee_org_id=None,
                        amount=Decimal("10.00"),
                        currency="USD",
                        platform_commission=Decimal("0.00"),
                        net_amount=Decimal("10.00"),
                        transaction_type="purchase",
                        status="pending",
                    )
                )
                await session.flush()


@pytest.mark.asyncio
async def test_create_org_payment_method_setup_requires_actor_totp(
    migrated_database: None,
    org_billing_state: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Org payment-method setup is blocked when the admin has not enabled 2FA."""
    del migrated_database
    import app.modules.organizations.billing_service as billing_service

    owner, _unused_secret = await _create_user(
        "org-billing-owner",
        enable_totp=False,
    )
    org = await _create_org(owner)
    customer_calls: list[str] = []

    async def fake_create_customer(
        *,
        email: str,
        name: str | None = None,
        idempotency_key: str | None = None,
    ) -> FakeStripeCustomer:
        """Record unexpected customer creation attempts."""
        del email, name, idempotency_key
        customer_calls.append("called")
        return FakeStripeCustomer("cus_should_not_be_created")

    monkeypatch.setattr(billing_service.stripe, "create_customer", fake_create_customer)

    with pytest.raises(HTTPException) as exc_info:
        async with async_session_factory() as session:
            await billing_service.create_org_payment_method_setup(
                session,
                org_billing_state["redis"],
                org_id=org.id,
                actor=owner,
                totp_code="123456",
            )

    assert exc_info.value.status_code == 403
    assert customer_calls == []
