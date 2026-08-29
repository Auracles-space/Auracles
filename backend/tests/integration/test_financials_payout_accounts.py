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
from app.integrations.paystack import PaystackProviderError
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials import service as financials_service
from app.modules.financials.models import Payout, PayoutAccount, Transaction
from app.modules.frameworks.models import Framework, License
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for TOTP-sensitive payout-account routes."""

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


class FakePaystackRecipient:
    """Paystack transfer recipient test double."""

    def __init__(self, recipient_code: str, account_name: str) -> None:
        """Store the recipient code and bank-confirmed account name."""
        self.recipient_code = recipient_code
        self.account_name = account_name


@pytest.fixture
async def payout_account_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset auth/financial state and replace provider calls with doubles."""
    fake_redis = FakeRedis()
    calls: dict[str, list[Any]] = {
        "stripe_accounts": [],
        "stripe_links": [],
        "paystack_recipients": [],
    }
    failures: dict[str, bool] = {"paystack_recipient": False}

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

    async def fake_create_transfer_recipient(
        *,
        name: str,
        account_number: str,
        bank_code: str,
        currency: str,
    ) -> FakePaystackRecipient:
        """Record recipient registration and return a recipient code."""
        if failures["paystack_recipient"]:
            raise PaystackProviderError("Paystack rejected the account.")
        calls["paystack_recipients"].append(
            {
                "name": name,
                "account_number": account_number,
                "bank_code": bank_code,
                "currency": currency,
            }
        )
        return FakePaystackRecipient("RCP_test_9876", "ADA LOVELACE")

    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr(
        financials_service.paystack,
        "create_transfer_recipient",
        fake_create_transfer_recipient,
    )
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
        yield {"redis": fake_redis, "calls": calls, "failures": failures}
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
            "return_url": "https://auracles.space/dashboard/financials",
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
        "return_url": "https://auracles.space/dashboard/financials",
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
    """Onboarding twice for the same contributor reuses the existing payout account."""
    contributor_id, _ = await create_user_with_roles(
        "stripe-contributor-reuse@auracles.space",
        ["contributor"],
    )

    payload = {
        "provider": "stripe",
        "country": "US",
        "refresh_url": "https://auracles.space/settings/payout-accounts",
        "return_url": "https://auracles.space/dashboard/financials",
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

    # Stripe account creation called once; link creation called twice
    assert len(payout_account_context["calls"]["stripe_accounts"]) == 1
    assert len(payout_account_context["calls"]["stripe_links"]) == 2

    # Verify only one PayoutAccount exists in the database for this user
    async with async_session_factory() as session:
        accounts = (
            (
                await session.execute(
                    select(PayoutAccount).where(PayoutAccount.user_id == contributor_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(accounts) == 1


async def test_nigerian_contributor_onboards_a_paystack_payout_account(
    client: AsyncClient,
    migrated_database: None,
    payout_account_context: dict[str, Any],
) -> None:
    """A NG payout account registers a transfer recipient and verifies at once.

    Paystack has no hosted onboarding: the NUBAN details are submitted
    directly, and Paystack resolving them against the bank is what proves the
    account exists. There is no redirect and nothing to wait on, so the
    response carries no onboarding URL and the account is verified immediately.
    """
    contributor_id, _ = await create_user_with_roles(
        "ng-contributor@auracles.space",
        ["contributor"],
    )

    response = await client.post(
        "/v1/financials/payout-accounts/onboard",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "provider": "paystack",
            "country": "NG",
            "account_number": "0123456789",
            "bank_code": "044",
        },
    )

    async with async_session_factory() as session:
        payout_account = await session.scalar(select(PayoutAccount))

    body = response.json()
    assert response.status_code == 200
    assert body["provider"] == "paystack"
    assert body["onboarding_url"] is None
    # Surfaced so the Contributor can catch a mistyped account number before
    # any money is addressed to the recipient.
    assert body["account_name"] == "ADA LOVELACE"
    assert body["payout_account"]["account_type"] == "nuban"
    assert body["payout_account"]["provider_account_ref"] == "****9876"
    assert body["payout_account"]["verified_at"] is not None
    assert payout_account is not None
    # The recipient code is the payout address; it must never sit in plaintext.
    assert payout_account.provider_account_id != "RCP_test_9876"
    assert payout_account.provider_account_lookup_hash == (
        hash_payout_provider_account_id("RCP_test_9876")
    )
    assert payout_account_context["calls"]["paystack_recipients"] == [
        {
            "name": "ng-contributor",
            "account_number": "0123456789",
            "bank_code": "044",
            "currency": "USD",
        }
    ]


async def test_paystack_onboarding_rejects_a_country_that_settles_elsewhere(
    client: AsyncClient,
    migrated_database: None,
    payout_account_context: dict[str, Any],
) -> None:
    """The rail follows the country, so a mismatched provider is refused.

    Letting the caller pick would register a Nigerian bank account against
    Stripe Connect, which cannot pay it, and the money would strand.
    """
    contributor_id, _ = await create_user_with_roles(
        "mismatch-contributor@auracles.space",
        ["contributor"],
    )

    response = await client.post(
        "/v1/financials/payout-accounts/onboard",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "provider": "paystack",
            "country": "US",
            "account_number": "0123456789",
            "bank_code": "044",
        },
    )

    assert response.status_code == 422
    assert payout_account_context["calls"]["paystack_recipients"] == []


async def test_paystack_onboarding_requires_bank_details(
    client: AsyncClient,
    migrated_database: None,
    payout_account_context: dict[str, Any],
) -> None:
    """Without an account number there is nothing to register, so reject early.

    Caught by the schema so the request never reaches the provider and cannot
    leave a half-created recipient behind.
    """
    contributor_id, _ = await create_user_with_roles(
        "nodetails-contributor@auracles.space",
        ["contributor"],
    )

    response = await client.post(
        "/v1/financials/payout-accounts/onboard",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={"provider": "paystack", "country": "NG"},
    )

    assert response.status_code == 422
    assert payout_account_context["calls"]["paystack_recipients"] == []


async def test_paystack_onboarding_failure_stores_no_payout_account(
    client: AsyncClient,
    migrated_database: None,
    payout_account_context: dict[str, Any],
) -> None:
    """A rejected account must leave no row a payout could later be sent to."""
    contributor_id, _ = await create_user_with_roles(
        "rejected-contributor@auracles.space",
        ["contributor"],
    )
    payout_account_context["failures"]["paystack_recipient"] = True

    response = await client.post(
        "/v1/financials/payout-accounts/onboard",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "provider": "paystack",
            "country": "NG",
            "account_number": "0000000000",
            "bank_code": "044",
        },
    )

    async with async_session_factory() as session:
        payout_account = await session.scalar(select(PayoutAccount))

    assert response.status_code == 502
    assert payout_account is None


async def test_paystack_onboarding_reuses_an_existing_account(
    client: AsyncClient,
    migrated_database: None,
    payout_account_context: dict[str, Any],
) -> None:
    """Re-onboarding must not register a second recipient for the same person.

    Unlike Stripe there is no link to refresh, so the existing account is
    returned as-is and the provider is never called again.
    """
    contributor_id, _ = await create_user_with_roles(
        "repeat-ng-contributor@auracles.space",
        ["contributor"],
    )
    payload = {
        "provider": "paystack",
        "country": "NG",
        "account_number": "0123456789",
        "bank_code": "044",
    }
    headers = auth_headers(contributor_id, ["contributor"])

    first = await client.post(
        "/v1/financials/payout-accounts/onboard", headers=headers, json=payload
    )
    second = await client.post(
        "/v1/financials/payout-accounts/onboard", headers=headers, json=payload
    )

    async with async_session_factory() as session:
        accounts = (
            (
                await session.execute(
                    select(PayoutAccount).where(PayoutAccount.user_id == contributor_id)
                )
            )
            .scalars()
            .all()
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["payout_account"]["id"] == second.json()["payout_account"]["id"]
    assert len(accounts) == 1
    assert len(payout_account_context["calls"]["paystack_recipients"]) == 1
