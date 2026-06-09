"""Integration tests for audited admin platform configuration endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
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
from app.modules.financials.models import PlatformConfig
from app.shared.models.audit_log import AuditLog

DEFAULT_PLATFORM_CONFIG = {
    "commission_rate": "0.15",
    "min_payout_usd": "50",
    "min_payout_ngn": "20000",
    "refund_window_hours": "48",
}


class FakeRedis:
    """Redis test double for TOTP-sensitive admin config routes."""

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


async def reset_admin_config_state() -> None:
    """Restore platform config defaults and remove admin test identities."""
    async with async_session_factory() as session:
        async with session.begin():
            for key, value in DEFAULT_PLATFORM_CONFIG.items():
                config = await session.get(PlatformConfig, key)
                if config is None:
                    session.add(PlatformConfig(key=key, value=value, updated_by=None))
                else:
                    config.value = value
                    config.updated_by = None
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Phase 3 financial tables exist for admin config tests."""
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
async def admin_config_context() -> AsyncIterator[FakeRedis]:
    """Reset auth/config state and install Redis test double."""
    fake_redis = FakeRedis()
    await engine.dispose()
    await reset_admin_config_state()

    async def override_redis() -> FakeRedis:
        """Return the Redis test double for dependency injection."""
        return fake_redis

    app.dependency_overrides[get_redis] = override_redis
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await reset_admin_config_state()
        await engine.dispose()


async def create_admin_user(*, enable_totp: bool = True) -> tuple[UUID, str | None]:
    """Create an admin user and optional encrypted TOTP secret."""
    secret = pyotp.random_base32() if enable_totp else None
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"config-admin-{uuid4()}@auracles.space",
                password_hash="not-used",
                display_name="Config Admin",
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


def auth_headers(user_id: UUID) -> dict[str, str]:
    """Create admin bearer auth headers for tests."""
    token = create_access_token(user_id=user_id, roles=["admin"])
    return {"Authorization": f"Bearer {token}"}


async def test_admin_can_read_platform_config(
    client: AsyncClient,
    migrated_database: None,
    admin_config_context: FakeRedis,
) -> None:
    """Admin users can inspect active platform financial configuration."""
    del migrated_database, admin_config_context
    admin_id, _ = await create_admin_user(enable_totp=False)

    response = await client.get(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
    )

    assert response.status_code == 200
    config = {item["key"]: item for item in response.json()["items"]}
    assert config["commission_rate"]["value"] == "0.15"
    assert config["min_payout_usd"]["value"] == "50"
    assert config["refund_window_hours"]["value"] == "48"
    assert config["commission_rate"]["editable"] is True
    assert config["min_payout_ngn"]["editable"] is False


async def test_admin_updates_editable_config_with_totp_reason_and_audit(
    client: AsyncClient,
    migrated_database: None,
    admin_config_context: FakeRedis,
) -> None:
    """Admin config changes require 2FA and audit each changed key."""
    del migrated_database, admin_config_context
    admin_id, totp_secret = await create_admin_user()
    assert totp_secret is not None

    response = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Lower initial launch commission and extend refund window.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [
                {"key": "commission_rate", "value": "0.12"},
                {"key": "refund_window_hours", "value": "72"},
            ],
        },
    )

    async with async_session_factory() as session:
        config_rows = {
            row.key: row
            for row in (
                await session.execute(select(PlatformConfig))
            ).scalars().all()
        }
        audits = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.action == "platform_config_updated")
                .order_by(AuditLog.created_at)
            )
        ).scalars().all()

    assert response.status_code == 200
    response_config = {item["key"]: item for item in response.json()["items"]}
    assert response_config["commission_rate"]["value"] == "0.12"
    assert response_config["refund_window_hours"]["value"] == "72"
    assert config_rows["commission_rate"].value == "0.12"
    assert config_rows["commission_rate"].updated_by == admin_id
    assert config_rows["refund_window_hours"].value == "72"
    assert config_rows["refund_window_hours"].updated_by == admin_id
    assert len(audits) == 2
    assert {audit.metadata_["key"] for audit in audits} == {
        "commission_rate",
        "refund_window_hours",
    }
    assert {
        audit.metadata_["reason"] for audit in audits
    } == {"Lower initial launch commission and extend refund window."}
    assert {
        audit.metadata_["old_value"] for audit in audits
    } == {"0.15", "48"}
    assert {
        audit.metadata_["new_value"] for audit in audits
    } == {"0.12", "72"}


async def test_admin_config_rejects_invalid_2fa_ranges_and_uneditable_keys(
    client: AsyncClient,
    migrated_database: None,
    admin_config_context: FakeRedis,
) -> None:
    """Rejected config changes do not mutate config or create audit rows."""
    del migrated_database, admin_config_context
    admin_id, totp_secret = await create_admin_user()
    assert totp_secret is not None

    invalid_2fa = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Should not pass.",
            "totp_code": "000000",
            "updates": [{"key": "commission_rate", "value": "0.10"}],
        },
    )
    out_of_range = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Should not pass.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [{"key": "commission_rate", "value": "0.75"}],
        },
    )
    uneditable_key = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Paystack is deferred.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [{"key": "min_payout_ngn", "value": "30000"}],
        },
    )

    async with async_session_factory() as session:
        commission_rate = await session.get(PlatformConfig, "commission_rate")
        min_payout_ngn = await session.get(PlatformConfig, "min_payout_ngn")
        audit_count = len(
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "platform_config_updated"
                    )
                )
            ).scalars().all()
        )

    assert invalid_2fa.status_code == 422
    assert out_of_range.status_code == 422
    assert uneditable_key.status_code == 422
    assert commission_rate is not None
    assert commission_rate.value == "0.15"
    assert min_payout_ngn is not None
    assert min_payout_ngn.value == "20000"
    assert audit_count == 0
