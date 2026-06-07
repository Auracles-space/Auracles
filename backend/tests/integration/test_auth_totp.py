"""Integration tests for TOTP setup, login challenge, and backup codes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, decode_access_token, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for 2FA challenge tokens and rate limits."""

    def __init__(self) -> None:
        """Create empty Redis-like storage."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}
        self.sets: dict[str, set[str]] = {}

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a string value with a TTL."""
        self.values[key] = value
        self.ttls[key] = seconds

    async def get(self, key: str) -> str | None:
        """Return a stored string or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def delete(self, *keys: str) -> int:
        """Delete keys and return the count removed."""
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.sets)
            self.values.pop(key, None)
            self.ttls.pop(key, None)
            self.sets.pop(key, None)
        return removed

    async def incr(self, key: str) -> int:
        """Increment and return a counter."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """Record a TTL for any Redis key shape used in auth."""
        self.ttls[key] = seconds

    async def ttl(self, key: str) -> int:
        """Return a recorded TTL or Redis' no-expiry sentinel."""
        return self.ttls.get(key, -1)

    async def sadd(self, key: str, *values: str) -> int:
        """Add values to a Redis set."""
        existing = self.sets.setdefault(key, set())
        before = len(existing)
        existing.update(values)
        return len(existing) - before

    async def srem(self, key: str, *values: str) -> int:
        """Remove values from a Redis set."""
        existing = self.sets.setdefault(key, set())
        before = len(existing)
        existing.difference_update(values)
        return before - len(existing)

    async def smembers(self, key: str) -> set[str]:
        """Return Redis set members."""
        return set(self.sets.get(key, set()))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure auth tables exist for TOTP tests."""
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
async def totp_test_context() -> AsyncIterator[dict[str, Any]]:
    """Reset auth tables and install fake Redis."""
    fake_redis = FakeRedis()
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()

    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield {"redis": fake_redis}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await engine.dispose()


async def create_verified_user(email: str, password: str) -> UUID:
    """Create a verified operator account for TOTP API tests."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password(password),
                display_name=email.split("@")[0],
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(
                    user_id=user.id,
                    role="operator",
                    approved_at=datetime.now(UTC),
                )
            )
        return user.id


def auth_headers(user_id: UUID) -> dict[str, str]:
    """Create bearer auth headers for a verified operator."""
    token = create_access_token(user_id=user_id, roles=["operator"])
    return {"Authorization": f"Bearer {token}"}


def secret_from_uri(provisioning_uri: str) -> str:
    """Extract a TOTP secret from an otpauth provisioning URI."""
    parsed = urlparse(provisioning_uri)
    values = parse_qs(parsed.query)
    return values["secret"][0]


async def setup_and_enable_totp(client: AsyncClient, user_id: UUID) -> dict[str, Any]:
    """Enable TOTP through public endpoints and return the setup response body."""
    setup = await client.post(
        "/v1/auth/2fa/setup",
        headers=auth_headers(user_id),
    )
    body = setup.json()
    code = pyotp.TOTP(secret_from_uri(body["provisioning_uri"])).now()
    verified = await client.post(
        "/v1/auth/2fa/verify",
        json={"code": code},
        headers=auth_headers(user_id),
    )
    assert setup.status_code == 200
    assert verified.status_code == 200
    return body


async def test_user_can_setup_and_enable_totp_with_backup_codes(
    client: AsyncClient,
    migrated_database: None,
    totp_test_context: dict[str, Any],
) -> None:
    """Setup returns one-time recovery material, and a valid TOTP enables 2FA."""
    user_id = await create_verified_user("totp@auracles.space", "CorrectHorse9")

    setup = await client.post(
        "/v1/auth/2fa/setup",
        headers=auth_headers(user_id),
    )
    body = setup.json()
    code = pyotp.TOTP(secret_from_uri(body["provisioning_uri"])).now()
    verified = await client.post(
        "/v1/auth/2fa/verify",
        json={"code": code},
        headers=auth_headers(user_id),
    )

    async with async_session_factory() as session:
        user = await session.scalar(select(User).where(User.id == user_id))
        audit_log = await session.scalar(
            select(AuditLog).where(AuditLog.action == "2fa_enabled")
        )

    assert setup.status_code == 200
    assert body["provisioning_uri"].startswith("otpauth://totp/")
    assert body["qr_png_base64"]
    assert len(body["backup_codes"]) == 10
    assert len(set(body["backup_codes"])) == 10
    assert verified.status_code == 200
    assert verified.json()["totp_enabled"] is True
    assert user is not None
    assert user.totp_enabled is True
    assert user.totp_secret is not None
    assert audit_log is not None


async def test_totp_enabled_login_requires_challenge_before_session_tokens(
    client: AsyncClient,
    migrated_database: None,
    totp_test_context: dict[str, Any],
) -> None:
    """2FA-enabled login returns a challenge until the code is verified."""
    user_id = await create_verified_user("challenge@auracles.space", "CorrectHorse9")
    setup_body = await setup_and_enable_totp(client, user_id)

    login = await client.post(
        "/v1/auth/login",
        json={"email": "challenge@auracles.space", "password": "CorrectHorse9"},
    )
    challenge_body = login.json()
    code = pyotp.TOTP(secret_from_uri(setup_body["provisioning_uri"])).now()
    verified = await client.post(
        "/v1/auth/2fa/verify-login",
        json={"challenge_token": challenge_body["challenge_token"], "code": code},
    )
    verified_body = verified.json()
    payload = decode_access_token(verified_body["access_token"])
    async with async_session_factory() as session:
        audit_log = await session.scalar(
            select(AuditLog).where(AuditLog.action == "new_device_login")
        )

    assert login.status_code == 200
    assert challenge_body["requires_2fa"] is True
    assert "access_token" not in challenge_body
    assert login.cookies.get("refresh_token") is None
    assert verified.status_code == 200
    assert verified.cookies.get("refresh_token") is not None
    assert verified.cookies.get("session_hint") is not None
    assert payload.sub == user_id
    assert payload.totp_verified is True
    assert audit_log is not None


async def test_backup_code_completes_login_once(
    client: AsyncClient,
    migrated_database: None,
    totp_test_context: dict[str, Any],
) -> None:
    """Backup codes can satisfy one login challenge and cannot be reused."""
    user_id = await create_verified_user("backup@auracles.space", "CorrectHorse9")
    setup_body = await setup_and_enable_totp(client, user_id)
    backup_code = setup_body["backup_codes"][0]

    first_login = await client.post(
        "/v1/auth/login",
        json={"email": "backup@auracles.space", "password": "CorrectHorse9"},
    )
    first_verified = await client.post(
        "/v1/auth/2fa/verify-login",
        json={
            "challenge_token": first_login.json()["challenge_token"],
            "code": backup_code,
        },
    )
    second_login = await client.post(
        "/v1/auth/login",
        json={"email": "backup@auracles.space", "password": "CorrectHorse9"},
    )
    reused = await client.post(
        "/v1/auth/2fa/verify-login",
        json={
            "challenge_token": second_login.json()["challenge_token"],
            "code": backup_code,
        },
    )

    assert first_verified.status_code == 200
    assert reused.status_code == 422


async def test_disable_totp_restores_password_only_login(
    client: AsyncClient,
    migrated_database: None,
    totp_test_context: dict[str, Any],
) -> None:
    """A valid current TOTP code disables 2FA and audits the change."""
    user_id = await create_verified_user("disable@auracles.space", "CorrectHorse9")
    setup_body = await setup_and_enable_totp(client, user_id)
    code = pyotp.TOTP(secret_from_uri(setup_body["provisioning_uri"])).now()

    disabled = await client.post(
        "/v1/auth/2fa/disable",
        json={"code": code},
        headers=auth_headers(user_id),
    )
    login = await client.post(
        "/v1/auth/login",
        json={"email": "disable@auracles.space", "password": "CorrectHorse9"},
    )

    async with async_session_factory() as session:
        user = await session.scalar(select(User).where(User.id == user_id))
        audit_log = await session.scalar(
            select(AuditLog).where(AuditLog.action == "2fa_disabled")
        )

    assert disabled.status_code == 200
    assert disabled.json()["totp_enabled"] is False
    assert login.status_code == 200
    assert login.json()["access_token"]
    assert "challenge_token" not in login.json()
    assert user is not None
    assert user.totp_enabled is False
    assert user.totp_secret is None
    assert audit_log is not None


async def test_totp_wrong_code_attempts_are_rate_limited(
    client: AsyncClient,
    migrated_database: None,
    totp_test_context: dict[str, Any],
) -> None:
    """Six wrong TOTP attempts inside the lockout window return 429."""
    user_id = await create_verified_user("locked-2fa@auracles.space", "CorrectHorse9")
    await setup_and_enable_totp(client, user_id)

    for _attempt in range(5):
        response = await client.post(
            "/v1/auth/2fa/disable",
            json={"code": "000000"},
            headers=auth_headers(user_id),
        )
        assert response.status_code == 422

    locked = await client.post(
        "/v1/auth/2fa/disable",
        json={"code": "000000"},
        headers=auth_headers(user_id),
    )

    assert locked.status_code == 429


async def test_totp_login_challenge_is_single_use(
    client: AsyncClient,
    migrated_database: None,
    totp_test_context: dict[str, Any],
) -> None:
    """A consumed or missing 2FA login challenge returns Gone."""
    user_id = await create_verified_user("single-use@auracles.space", "CorrectHorse9")
    setup_body = await setup_and_enable_totp(client, user_id)
    login = await client.post(
        "/v1/auth/login",
        json={"email": "single-use@auracles.space", "password": "CorrectHorse9"},
    )
    challenge_token = login.json()["challenge_token"]
    code = pyotp.TOTP(secret_from_uri(setup_body["provisioning_uri"])).now()

    verified = await client.post(
        "/v1/auth/2fa/verify-login",
        json={"challenge_token": challenge_token, "code": code},
    )
    reused = await client.post(
        "/v1/auth/2fa/verify-login",
        json={"challenge_token": challenge_token, "code": code},
    )
    missing = await client.post(
        "/v1/auth/2fa/verify-login",
        json={"challenge_token": "missing", "code": code},
    )

    assert verified.status_code == 200
    assert reused.status_code == 410
    assert missing.status_code == 410
