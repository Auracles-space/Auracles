"""Money paths on the platform's real settlement currency.

`tests/conftest.py` pins the whole suite to `PLATFORM_CURRENCY=USD`, while
staging and production settle in NGN. `select_provider` routes on currency, so
under that pin Stripe is the correct rail for everything — and a money path
that never asks which rail to use looks identical to one that does.

That is not a theoretical gap. Two purchase endpoints shipped hardcoded to
Stripe and could not complete a sale in the pilot currency, because Stripe will
not render an NGN PaymentIntent: the API returns a client secret and the buyer
waits forever. Both passed the suite.

These tests pin NGN for themselves and assert the rail, not the status code.
Anything that decides a payment rail, a fee, or a payout destination belongs
here.
"""

from __future__ import annotations

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
from app.core.security import create_access_token, hash_password
from app.integrations import paystack
from app.modules.auth.models import User, UserRole
from app.modules.collections.models import CollectionFramework, FrameworkCollection
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework


@pytest.fixture(autouse=True)
async def naira_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[None]:
    """Run these tests on the currency the platform actually settles in.

    Also drops the process-wide connection pools, which outlive a single test
    and would otherwise be reused against a closed event loop.
    """
    await engine.dispose()
    get_redis.cache_clear()
    monkeypatch.setenv("PLATFORM_CURRENCY", "NGN")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()
    get_redis.cache_clear()


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    return {
        "Authorization": f"Bearer {create_access_token(user_id=user_id, roles=roles)}"
    }


async def _seed(slug: str) -> dict[str, Any]:
    """Create an Operator, a Contributor, two NGN Frameworks and a bundle."""
    async with async_session_factory() as session:
        async with session.begin():
            contributor = User(
                email=f"ngn-seller-{slug}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Naira Seller",
                email_verified=True,
                kyc_status="verified",
            )
            operator = User(
                email=f"ngn-buyer-{slug}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Naira Buyer",
                email_verified=True,
                kyc_status="verified",
            )
            session.add_all([contributor, operator])
            await session.flush()
            session.add_all(
                [
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
            framework_ids: list[UUID] = []
            for index in range(2):
                framework = Framework(
                    contributor_id=contributor.id,
                    title=f"Naira Framework {index} {slug}",
                    description="Priced in the platform settlement currency.",
                    status="published",
                    category="operations",
                    sector="technology",
                    industry="software",
                    business_function="revenue_operations",
                    tags=["ngn"],
                    tags_text="ngn",
                    price=Decimal("250000.00"),
                    currency="NGN",
                    license_types=["single_user"],
                    published_at=datetime.now(UTC),
                )
                session.add(framework)
                await session.flush()
                framework_ids.append(framework.id)

            collection = FrameworkCollection(
                contributor_id=contributor.id,
                title=f"Naira Bundle {slug}",
                description="A discounted set of Frameworks priced in naira.",
                bundle_price=Decimal("400000.00"),
                currency="NGN",
                status="published",
            )
            session.add(collection)
            await session.flush()
            for framework_id in framework_ids:
                session.add(
                    CollectionFramework(
                        collection_id=collection.id,
                        framework_id=framework_id,
                    )
                )
            return {
                "operator_id": operator.id,
                "framework_id": framework_ids[0],
                "collection_id": collection.id,
            }


def _fake_paystack(recorder: dict[str, Any]) -> Any:
    """Build a Paystack initializer that records its arguments."""

    async def fake_initialize_transaction(
        *,
        email: str,
        amount: Decimal,
        currency: str,
        metadata: dict[str, str],
        callback_url: str | None = None,
    ) -> paystack.PaystackInitializedTransaction:
        """Return a deterministic hosted checkout without network access."""
        recorder.update(
            {
                "email": email,
                "amount": amount,
                "currency": currency,
                "metadata": metadata,
                "callback_url": callback_url,
            }
        )
        return paystack.PaystackInitializedTransaction(
            reference="ref_ngn_pilot",
            authorization_url="https://checkout.paystack.com/ref_ngn_pilot",
            access_code="acc_ngn_pilot",
        )

    return fake_initialize_transaction


async def test_framework_purchase_settles_on_paystack(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Framework bought in naira must initialize on the local rail."""
    seeded = await _seed("framework")
    recorder: dict[str, Any] = {}
    monkeypatch.setattr(paystack, "initialize_transaction", _fake_paystack(recorder))

    response = await client.post(
        f"/v1/financials/purchase/{seeded['framework_id']}",
        headers=auth_headers(seeded["operator_id"], ["operator"]),
        json={"license_type": "single_user", "country": "NG"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "paystack"
    assert body["authorization_url"] is not None
    assert recorder["currency"] == "NGN"


async def test_collection_purchase_settles_on_paystack(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Collection bundle bought in naira must initialize on the local rail.

    The bundle path hardcoded Stripe, so in the pilot currency it returned a
    PaymentIntent that Stripe Elements refuses to render — a bundle that could
    be listed and priced but never bought.
    """
    seeded = await _seed("collection")
    recorder: dict[str, Any] = {}
    monkeypatch.setattr(paystack, "initialize_transaction", _fake_paystack(recorder))

    response = await client.post(
        f"/v1/financials/collections/{seeded['collection_id']}/purchase",
        headers=auth_headers(seeded["operator_id"], ["operator"]),
        json={"license_type": "single_user", "country": "NG"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "paystack"
    assert body["authorization_url"] is not None
    assert body.get("client_secret") is None
    assert recorder["currency"] == "NGN"

    async with async_session_factory() as session:
        transaction = await session.scalar(
            select(Transaction).where(Transaction.id == UUID(body["transaction_id"]))
        )
    assert transaction is not None
    assert transaction.provider == "paystack"
