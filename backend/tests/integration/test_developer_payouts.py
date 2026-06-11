"""Integration tests for Phase 5a Partner payout workflows."""

from __future__ import annotations

import hashlib
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
from sqlalchemy import create_engine, delete, func, select

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
from app.modules.developer import commission_service
from app.modules.developer.models import (
    ApiKey,
    DeveloperAccount,
    DeveloperApplication,
    PartnerCommission,
    PartnerPayout,
)
from app.modules.financials.models import PayoutAccount, Transaction
from app.modules.frameworks.models import Framework
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for TOTP failure bookkeeping."""

    def __init__(self) -> None:
        """Create empty fake Redis state."""
        self.values: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

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


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Developer payout tables exist for endpoint tests."""
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
async def developer_payout_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset payout rows and replace Redis/task dispatch with test doubles."""
    fake_redis = FakeRedis()
    dispatched: list[str] = []
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in dependency order."""
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(delete(AuditLog))
                await session.execute(delete(PartnerCommission))
                await session.execute(delete(PartnerPayout))
                await session.execute(delete(PayoutAccount))
                await session.execute(delete(ApiKey))
                await session.execute(delete(DeveloperAccount))
                await session.execute(delete(DeveloperApplication))
                await session.execute(delete(Transaction))
                await session.execute(delete(Framework))
                await session.execute(delete(UserRole))
                await session.execute(delete(User))

    def fake_delay(payout_id: str) -> None:
        """Record Partner payout processing dispatch."""
        dispatched.append(payout_id)

    await cleanup()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr(
        commission_service.process_partner_payout,
        "delay",
        fake_delay,
    )
    try:
        yield {"redis": fake_redis, "dispatched": dispatched}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def create_partner_payout_fixture() -> tuple[UUID, UUID, UUID, str]:
    """Create verified Developer, payout account, and cleared commissions."""
    totp_secret = pyotp.random_base32()
    async with async_session_factory() as session:
        async with session.begin():
            developer = User(
                email=f"partner-payout-developer-{uuid4()}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Partner Payout Developer",
                email_verified=True,
                kyc_status="verified",
                totp_enabled=True,
                totp_secret=encrypt_totp_secret(totp_secret),
            )
            contributor = User(
                email=f"partner-payout-contributor-{uuid4()}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Partner Payout Contributor",
                email_verified=True,
            )
            operator = User(
                email=f"partner-payout-operator-{uuid4()}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Partner Payout Operator",
                email_verified=True,
            )
            session.add_all([developer, contributor, operator])
            await session.flush()
            session.add_all(
                [
                    UserRole(
                        user_id=developer.id,
                        role="developer",
                        approved_at=datetime.now(UTC),
                    ),
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
            application = DeveloperApplication(
                user_id=developer.id,
                company_name="Partner Payout Co.",
                website="https://partner-payout.example.com",
                use_case="Withdraw cleared partner commissions.",
                status="approved",
                reviewed_at=datetime.now(UTC),
            )
            session.add(application)
            await session.flush()
            account = DeveloperAccount(
                user_id=developer.id,
                application_id=application.id,
                company_name=application.company_name,
            )
            session.add(account)
            payout_account = PayoutAccount(
                user_id=developer.id,
                provider="stripe",
                provider_account_id=encrypt_payout_provider_account_id(
                    "acct_partner_payout_123"
                ),
                provider_account_lookup_hash=hash_payout_provider_account_id(
                    "acct_partner_payout_123"
                ),
                account_type="express",
                is_default=True,
                verified_at=datetime.now(UTC),
            )
            session.add(payout_account)
            await session.flush()
            api_key = ApiKey(
                developer_account_id=account.id,
                name="Partner payout key",
                key_prefix="ak_payout",
                key_hash=hashlib.sha256(b"partner-payout-key").hexdigest(),
                scopes=["purchase:write"],
            )
            framework = Framework(
                contributor_id=contributor.id,
                title="Partner Payout Framework",
                description="Framework used by Partner payout tests.",
                status="published",
                category="operations",
                tags=["payout"],
                tags_text="payout",
                price=Decimal("100.00"),
                currency="USD",
                license_types=["team"],
            )
            session.add_all([api_key, framework])
            await session.flush()
            for index, amount in enumerate((Decimal("30.00"), Decimal("25.00"))):
                transaction = Transaction(
                    payer_id=operator.id,
                    payee_id=contributor.id,
                    amount=Decimal("100.00"),
                    currency="USD",
                    platform_commission=Decimal("0.00"),
                    net_amount=Decimal("100.00"),
                    transaction_type="purchase",
                    status="completed",
                    provider="stripe",
                    provider_ref=f"pi_partner_payout_{index}_{uuid4()}",
                    ref_id=framework.id,
                    ref_type="framework",
                )
                session.add(transaction)
                await session.flush()
                session.add(
                    PartnerCommission(
                        api_key_id=api_key.id,
                        developer_account_id=account.id,
                        transaction_id=transaction.id,
                        framework_id=framework.id,
                        sale_amount=Decimal("100.00"),
                        currency="USD",
                        tier_at_sale=1,
                        tier_rate=Decimal("0.0500"),
                        commission_amount=amount,
                        status="cleared",
                        cleared_at=datetime.now(UTC),
                    )
                )
            return developer.id, account.id, payout_account.id, totp_secret


def auth_headers(user_id: UUID) -> dict[str, str]:
    """Create Developer bearer auth headers."""
    token = create_access_token(user_id=user_id, roles=["developer"])
    return {"Authorization": f"Bearer {token}"}


async def test_developer_requests_partner_payout_and_lists_history(
    client: AsyncClient,
    migrated_database: None,
    developer_payout_context: dict[str, Any],
) -> None:
    """Verified Developer can withdraw full cleared Partner commission balance."""
    del migrated_database
    user_id, _account_id, payout_account_id, totp_secret = (
        await create_partner_payout_fixture()
    )

    response = await client.post(
        "/v1/developer/payouts",
        headers=auth_headers(user_id),
        json={
            "amount": "55.00",
            "currency": "USD",
            "payout_account_id": str(payout_account_id),
            "totp_code": pyotp.TOTP(totp_secret).now(),
        },
    )
    listed = await client.get(
        "/v1/developer/payouts",
        headers=auth_headers(user_id),
    )

    assert response.status_code == 200
    body = response.json()
    payout_id = UUID(body["id"])
    assert body["amount"] == "55.00"
    assert body["status"] == "pending"
    assert listed.status_code == 200
    assert listed.json()["payouts"][0]["id"] == str(payout_id)
    assert developer_payout_context["dispatched"] == [str(payout_id)]

    async with async_session_factory() as session:
        payout = await session.get(PartnerPayout, payout_id)
        commission_count = await session.scalar(
            select(func.count(PartnerCommission.id)).where(
                PartnerCommission.payout_id == payout_id
            )
        )
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "partner_payout_requested")
        )

    assert payout is not None
    assert payout.amount == Decimal("55.00")
    assert commission_count == 2
    assert audit is not None
    assert audit.target_id == payout_id
