"""Integration tests for Contributor payout-account onboarding."""

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
    encrypt_payout_provider_account_id,
    encrypt_totp_secret,
    hash_password,
    hash_payout_provider_account_id,
)
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials import service as financials_service
from app.modules.financials.models import Payout, PayoutAccount, Transaction
from app.modules.frameworks.models import Framework, License
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for TOTP-sensitive payout-account routes."""

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


class FakeStripeAccount:
    """Small stand-in for a Stripe Connect account result."""

    def __init__(self, account_id: str) -> None:
        """Store the provider account id."""
        self.id = account_id


class FakeStripeAccountLink:
    """Small stand-in for a Stripe Connect account link result."""

    def __init__(self, url: str) -> None:
        """Store the provider-hosted onboarding URL."""
        self.url = url


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure financial tables exist for payout-account tests."""
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
async def payout_account_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset auth/financial state and replace provider calls with doubles."""
    fake_redis = FakeRedis()
    calls: dict[str, list[Any]] = {
        "stripe_accounts": [],
        "stripe_links": [],
    }

    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(License))
        await session.execute(delete(Payout))
        await session.execute(delete(PayoutAccount))
        await session.execute(delete(Transaction))
        await session.execute(delete(Framework))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()

    async def fake_create_express_account(
        *,
        email: str,
        country: str,
    ) -> FakeStripeAccount:
        """Record Stripe account creation and return a provider id."""
        calls["stripe_accounts"].append({"email": email, "country": country})
        return FakeStripeAccount("acct_test_123")

    async def fake_create_account_link(
        *,
        account_id: str,
        refresh_url: str,
        return_url: str,
    ) -> FakeStripeAccountLink:
        """Record Stripe link creation and return an onboarding URL."""
        calls["stripe_links"].append(
            {
                "account_id": account_id,
                "refresh_url": refresh_url,
                "return_url": return_url,
            }
        )
        return FakeStripeAccountLink("https://connect.stripe.com/setup/test")

    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr(
        financials_service.stripe,
        "create_express_account",
        fake_create_express_account,
    )
    monkeypatch.setattr(
        financials_service.stripe,
        "create_account_link",
        fake_create_account_link,
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
    kyc_status: str = "verified",
    enable_totp: bool = True,
) -> tuple[UUID, str | None]:
    """Create a verified user with approved roles, KYC, and optional TOTP."""
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


async def test_contributor_can_onboard_stripe_express_payout_account(
    client: AsyncClient,
    migrated_database: None,
    payout_account_context: dict[str, Any],
) -> None:
    """Stripe onboarding stores a provider ref and returns a hosted link."""
    contributor_id, _ = await create_user_with_roles(
        "stripe-contributor@auracles.space",
        ["contributor"],
    )

    response = await client.post(
        "/v1/financials/payout-accounts/onboard",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "provider": "stripe",
            "country": "US",
            "refresh_url": "https://auracles.space/settings/payout-accounts",
            "return_url": "https://auracles.space/dashboard/payouts",
        },
    )

    async with async_session_factory() as session:
        payout_account = await session.scalar(select(PayoutAccount))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "payout_account_onboarded")
        )

    body = response.json()
    assert response.status_code == 200
    assert body["provider"] == "stripe"
    assert body["onboarding_url"] == "https://connect.stripe.com/setup/test"
    assert body["payout_account"]["provider"] == "stripe"
    assert body["payout_account"]["account_type"] == "express"
    assert body["payout_account"]["provider_account_ref"] == "****_123"
    assert body["payout_account"]["is_default"] is True
    assert payout_account is not None
    assert payout_account.provider_account_id != "acct_test_123"
    assert payout_account.provider_account_lookup_hash == (
        hash_payout_provider_account_id("acct_test_123")
    )
    assert audit is not None
    assert audit.metadata_["provider_account_ref"] == "****_123"


async def test_payout_account_onboarding_requires_contributor_and_kyc(
    client: AsyncClient,
    migrated_database: None,
    payout_account_context: dict[str, Any],
) -> None:
    """Only KYC-verified Contributors can create payout accounts."""
    pending_id, _ = await create_user_with_roles(
        "pending-contributor@auracles.space",
        ["contributor"],
        kyc_status="pending",
    )
    operator_id, _ = await create_user_with_roles(
        "operator-payout@auracles.space",
        ["operator"],
    )
    payload = {
        "provider": "stripe",
        "country": "US",
        "refresh_url": "https://auracles.space/settings/payout-accounts",
        "return_url": "https://auracles.space/dashboard/payouts",
    }

    pending_kyc = await client.post(
        "/v1/financials/payout-accounts/onboard",
        headers=auth_headers(pending_id, ["contributor"]),
        json=payload,
    )
    wrong_role = await client.post(
        "/v1/financials/payout-accounts/onboard",
        headers=auth_headers(operator_id, ["operator"]),
        json=payload,
    )

    assert pending_kyc.status_code == 403
    assert wrong_role.status_code == 403


async def test_contributor_lists_and_soft_deletes_payout_account_with_totp(
    client: AsyncClient,
    migrated_database: None,
    payout_account_context: dict[str, Any],
) -> None:
    """Contributor can list active payout accounts and soft-delete with 2FA."""
    contributor_id, totp_secret = await create_user_with_roles(
        "delete-payout@auracles.space",
        ["contributor"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                PayoutAccount(
                    user_id=contributor_id,
                    provider="stripe",
                    provider_account_id=encrypt_payout_provider_account_id(
                        "acct_delete_123"
                    ),
                    provider_account_lookup_hash=hash_payout_provider_account_id(
                        "acct_delete_123"
                    ),
                    account_type="express",
                    is_default=True,
                )
            )
    code = pyotp.TOTP(totp_secret).now()

    listed = await client.get(
        "/v1/financials/payout-accounts",
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    account_id = listed.json()["payout_accounts"][0]["id"]
    deleted = await client.request(
        "DELETE",
        f"/v1/financials/payout-accounts/{account_id}",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={"totp_code": code},
    )
    listed_after_delete = await client.get(
        "/v1/financials/payout-accounts",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    async with async_session_factory() as session:
        payout_account = await session.get(PayoutAccount, UUID(account_id))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "payout_account_deleted")
        )

    assert listed.status_code == 200
    assert listed.json()["payout_accounts"][0]["provider_account_ref"] == "****_123"
    assert deleted.status_code == 200
    assert deleted.json() == {
        "payout_account_id": account_id,
        "deleted": True,
    }
    assert listed_after_delete.json() == {"payout_accounts": []}
    assert payout_account is not None
    assert payout_account.deleted_at is not None
    assert audit is not None


async def test_payout_account_onboarding_reuses_existing_account(
    client: AsyncClient,
    migrated_database: None,
    payout_account_context: dict[str, Any],
) -> None:
    """Initiating onboarding twice for the same contributor reuses the existing payout account."""
    contributor_id, _ = await create_user_with_roles(
        "stripe-contributor-reuse@auracles.space",
        ["contributor"],
    )

    payload = {
        "provider": "stripe",
        "country": "US",
        "refresh_url": "https://auracles.space/settings/payout-accounts",
        "return_url": "https://auracles.space/dashboard/payouts",
    }

    # First onboarding call
    response1 = await client.post(
        "/v1/financials/payout-accounts/onboard",
        headers=auth_headers(contributor_id, ["contributor"]),
        json=payload,
    )
    assert response1.status_code == 200
    body1 = response1.json()
    account_id_1 = body1["payout_account"]["id"]

    # Second onboarding call (re-initiating)
    response2 = await client.post(
        "/v1/financials/payout-accounts/onboard",
        headers=auth_headers(contributor_id, ["contributor"]),
        json=payload,
    )
    assert response2.status_code == 200
    body2 = response2.json()
    account_id_2 = body2["payout_account"]["id"]

    # Assertions
    assert account_id_1 == account_id_2

    # Verify Stripe account creation was only called once, but link creation was called twice
    assert len(payout_account_context["calls"]["stripe_accounts"]) == 1
    assert len(payout_account_context["calls"]["stripe_links"]) == 2

    # Verify only one PayoutAccount exists in the database for this user
    async with async_session_factory() as session:
        accounts = (
            await session.execute(
                select(PayoutAccount).where(PayoutAccount.user_id == contributor_id)
            )
        ).scalars().all()
        assert len(accounts) == 1

