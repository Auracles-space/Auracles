"""Integration tests for Partner API payment-provider routing.

The Partner purchase endpoint must settle through the same rail as every other
money path: `select_provider` sends the Nigerian corridor to Paystack and
everything else to Stripe. These tests pin `PLATFORM_CURRENCY` explicitly
rather than inheriting the suite default, because the provider decision is
derived from currency and a suite-wide pin silently tests one branch twice.

Maps to: FR-DEV-014.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import hash_password
from app.integrations import paystack, stripe
from app.modules.auth.models import User, UserRole
from app.modules.developer.models import (
    ApiKey,
    DeveloperAccount,
    DeveloperApplication,
)
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework


def _raw_api_key(slug: str) -> str:
    """Build a deterministic raw API key unique to one test's fixtures."""
    return f"ak_partner_routing_{slug}_000000000000000000"


@pytest.fixture(autouse=True)
async def _reset_pooled_clients() -> AsyncIterator[None]:
    """Drop process-wide connection pools between tests in this module.

    Both the SQLAlchemy engine pool and the `lru_cache`d Redis client outlive a
    single test, so the second test here would reuse connections bound to the
    first test's event loop and die with `Event loop is closed` inside the
    buyer lookup — nowhere near the routing behaviour under test.
    """
    await engine.dispose()
    get_redis.cache_clear()
    yield
    get_redis.cache_clear()


@pytest.fixture
async def naira_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[None]:
    """Run one test on the production settlement currency.

    `tests/conftest.py` pins the suite to USD. Provider routing is decided from
    the currency, so a USD-only suite exercises the Stripe branch and reports
    the Paystack branch as covered.
    """
    monkeypatch.setenv("PLATFORM_CURRENCY", "NGN")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


async def _seed_partner_and_framework(
    *,
    slug: str,
    currency: str,
) -> dict[str, Any]:
    """Create an active Developer account, an API key, and a priced Framework.

    Args:
        slug: Discriminator making this test's users, emails and API key unique.
            The suite truncates between modules, not between tests, so two tests
            seeding the same addresses collide on the unique email index.
        currency: Settlement currency to price the Framework in, which is what
            the provider decision is derived from.
    """
    raw_api_key = _raw_api_key(slug)
    async with async_session_factory() as session:
        async with session.begin():
            developer = User(
                email=f"partner-routing-developer-{slug}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Partner Routing Developer",
                email_verified=True,
            )
            contributor = User(
                email=f"partner-routing-contributor-{slug}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Partner Routing Contributor",
                email_verified=True,
            )
            session.add_all([developer, contributor])
            await session.flush()
            session.add(
                UserRole(
                    user_id=contributor.id,
                    role="contributor",
                    approved_at=datetime.now(UTC),
                )
            )
            application = DeveloperApplication(
                user_id=developer.id,
                company_name="Partner Routing Ltd",
                use_case="Verify that Partner purchases settle on the local rail.",
                status="approved",
            )
            session.add(application)
            await session.flush()
            account = DeveloperAccount(
                user_id=developer.id,
                application_id=application.id,
                company_name="Partner Routing Ltd",
                commission_tier=1,
                tier_rate=Decimal("0.0500"),
                approved_at=datetime.now(UTC),
            )
            session.add(account)
            await session.flush()
            session.add(
                ApiKey(
                    developer_account_id=account.id,
                    name="Routing test key",
                    key_prefix=raw_api_key[:12],
                    key_hash=hashlib.sha256(raw_api_key.encode()).hexdigest(),
                    scopes=["catalog:read", "purchase:write"],
                )
            )
            framework = Framework(
                contributor_id=contributor.id,
                title="Partner Routing Framework",
                description="Framework priced in the platform settlement currency.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["partner", "routing"],
                tags_text="partner routing",
                price=Decimal("400000.00"),
                currency=currency,
                license_types=["single_user"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            return {
                "framework_id": framework.id,
                "developer_id": developer.id,
                "raw_api_key": raw_api_key,
            }


async def test_partner_purchase_settles_naira_on_paystack(
    client: AsyncClient,
    naira_platform: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Partner purchase in the platform currency must initialize on Paystack.

    Enforces the routing rule in `integrations/payment_router.select_provider`:
    the Nigerian corridor settles locally. Charging Stripe instead produces a
    PaymentIntent no card form can render, so the buyer is stranded.
    """
    del naira_platform
    seeded = await _seed_partner_and_framework(slug="ngn", currency="NGN")
    initialized: dict[str, Any] = {}

    async def fake_initialize_transaction(
        *,
        email: str,
        amount: Decimal,
        currency: str,
        metadata: dict[str, str],
        callback_url: str | None = None,
    ) -> paystack.PaystackInitializedTransaction:
        """Record the initialization and return a deterministic checkout."""
        initialized.update(
            {
                "email": email,
                "amount": amount,
                "currency": currency,
                "metadata": metadata,
                "callback_url": callback_url,
            }
        )
        return paystack.PaystackInitializedTransaction(
            reference="ref_partner_routing",
            authorization_url="https://checkout.paystack.com/ref_partner_routing",
            access_code="acc_partner_routing",
        )

    monkeypatch.setattr(paystack, "initialize_transaction", fake_initialize_transaction)

    response = await client.post(
        f"/v1/partner/frameworks/{seeded['framework_id']}/purchase",
        headers={"X-API-Key": seeded["raw_api_key"]},
        json={
            "buyer_email": "partner-routing-buyer-ngn@auracles.space",
            "license_type": "single_user",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "paystack"
    assert body["authorization_url"] == (
        "https://checkout.paystack.com/ref_partner_routing"
    )
    # Stripe's in-page handoff must be absent, not empty: a Partner branching on
    # truthiness of `client_secret` would otherwise mount an unusable card form.
    assert body.get("client_secret") is None
    assert initialized["currency"] == "NGN"
    # Without a callback URL Paystack keeps the payer on its own success page,
    # where a buyer who has already paid can pay a second time.
    assert initialized["callback_url"] is not None
    assert body["transaction_id"] in initialized["callback_url"]

    async with async_session_factory() as session:
        transaction = await session.scalar(
            select(Transaction).where(Transaction.id == UUID(body["transaction_id"]))
        )
    assert transaction is not None
    assert transaction.provider == "paystack"


async def test_partner_purchase_settles_dollars_on_stripe(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Partner purchase outside the Nigerian corridor still settles on Stripe.

    The Paystack branch must not swallow the card rail: this test inherits the
    suite's USD pin deliberately, so the two tests together cover both sides of
    `select_provider` rather than one branch twice.
    """
    seeded = await _seed_partner_and_framework(slug="usd", currency="USD")

    async def fake_create_customer(
        *,
        email: str,
        name: str,
        idempotency_key: str,
    ) -> Any:
        """Return a deterministic Stripe customer without network access."""
        del email, name, idempotency_key
        return type("FakeCustomer", (), {"id": "cus_partner_routing"})()

    async def fake_create_payment_intent(
        *,
        customer_id: str,
        amount: Decimal,
        currency: str,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> Any:
        """Return a deterministic PaymentIntent without network access."""
        del customer_id, amount, currency, idempotency_key
        return type(
            "FakeIntent",
            (),
            {
                "id": "pi_partner_routing",
                "client_secret": f"secret_{metadata['transaction_id']}",
            },
        )()

    monkeypatch.setattr(stripe, "create_customer", fake_create_customer)
    monkeypatch.setattr(stripe, "create_payment_intent", fake_create_payment_intent)

    response = await client.post(
        f"/v1/partner/frameworks/{seeded['framework_id']}/purchase",
        headers={"X-API-Key": seeded["raw_api_key"]},
        json={
            "buyer_email": "partner-routing-buyer-usd@auracles.space",
            "license_type": "single_user",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "stripe"
    assert body["client_secret"] is not None
    assert body.get("authorization_url") is None
