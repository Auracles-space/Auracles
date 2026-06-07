"""Integration tests for password reset and new-device login notifications."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import hash_password, verify_password
from app.main import app
from app.modules.auth import service as auth_service
from app.modules.auth.models import User, UserRole
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for reset tokens, sessions, and device fingerprints."""

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
            removed += int(
                key in self.values or key in self.sets or key in self.counters
            )
            self.values.pop(key, None)
            self.ttls.pop(key, None)
            self.sets.pop(key, None)
            self.counters.pop(key, None)
        return removed

    async def incr(self, key: str) -> int:
        """Increment and return a counter."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """Record a TTL for string, set, or counter keys."""
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

    async def sismember(self, key: str, value: str) -> int:
        """Return whether a value exists in a Redis set."""
        return int(value in self.sets.get(key, set()))


class SentEmails:
    """Capture password reset and device notification task dispatches."""

    def __init__(self) -> None:
        """Create empty dispatch recorders."""
        self.reset_calls: list[dict[str, str]] = []
        self.device_calls: list[dict[str, str]] = []

    def reset_delay(self, email: str, token: str) -> None:
        """Record a password reset email task dispatch."""
        self.reset_calls.append({"email": email, "token": token})

    def device_delay(self, email: str, ip: str | None, user_agent: str | None) -> None:
        """Record a new-device email task dispatch."""
        self.device_calls.append(
            {
                "email": email,
                "ip": ip or "",
                "user_agent": user_agent or "",
            }
        )


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure auth tables exist for reset tests."""
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
async def reset_test_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset auth tables and install Redis/email test doubles."""
    fake_redis = FakeRedis()
    sent_emails = SentEmails()
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()

    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr(
        auth_service.send_password_reset_email,
        "delay",
        sent_emails.reset_delay,
    )
    monkeypatch.setattr(
        auth_service.send_new_device_email,
        "delay",
        sent_emails.device_delay,
    )
    try:
        yield {"redis": fake_redis, "sent_emails": sent_emails}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await engine.dispose()


async def create_verified_user(email: str, password: str) -> UUID:
    """Create a verified operator for password reset tests."""
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


async def test_forgot_password_is_no_enumeration_and_sends_reset_for_known_email(
    client: AsyncClient,
    migrated_database: None,
    reset_test_context: dict[str, Any],
) -> None:
    """Forgot password always returns 200 but only emails existing users."""
    await create_verified_user("reset@auracles.space", "CorrectHorse9")

    known = await client.post(
        "/v1/auth/forgot-password",
        json={"email": "RESET@auracles.space"},
    )
    unknown = await client.post(
        "/v1/auth/forgot-password",
        json={"email": "unknown@auracles.space"},
    )

    sent_emails = reset_test_context["sent_emails"]
    fake_redis = reset_test_context["redis"]

    assert known.status_code == 200
    assert unknown.status_code == 200
    assert known.json() == {"message": "If email is valid, reset link sent."}
    assert unknown.json() == {"message": "If email is valid, reset link sent."}
    assert sent_emails.reset_calls == [
        {"email": "reset@auracles.space", "token": sent_emails.reset_calls[0]["token"]}
    ]
    assert sent_emails.reset_calls[0]["token"].startswith("pr_")
    assert 900 in set(fake_redis.ttls.values())


async def test_reset_password_changes_password_consumes_token_and_revokes_sessions(
    client: AsyncClient,
    migrated_database: None,
    reset_test_context: dict[str, Any],
) -> None:
    """Password reset updates the hash and revokes existing refresh sessions."""
    user_id = await create_verified_user("change@auracles.space", "CorrectHorse9")
    login = await client.post(
        "/v1/auth/login",
        json={"email": "change@auracles.space", "password": "CorrectHorse9"},
        headers={"User-Agent": "Old Browser"},
    )
    old_refresh = login.cookies["refresh_token"]
    await client.post(
        "/v1/auth/forgot-password",
        json={"email": "change@auracles.space"},
    )
    token = reset_test_context["sent_emails"].reset_calls[0]["token"]

    reset = await client.post(
        "/v1/auth/reset-password",
        json={"token": token, "new_password": "NewCorrectHorse9"},
    )
    reused = await client.post(
        "/v1/auth/reset-password",
        json={"token": token, "new_password": "AnotherCorrectHorse9"},
    )
    client.cookies.set("refresh_token", old_refresh)
    old_session = await client.post("/v1/auth/refresh")
    new_login = await client.post(
        "/v1/auth/login",
        json={"email": "change@auracles.space", "password": "NewCorrectHorse9"},
    )

    async with async_session_factory() as session:
        user = await session.scalar(select(User).where(User.id == user_id))
        audit_log = await session.scalar(
            select(AuditLog).where(AuditLog.action == "password_reset")
        )

    assert reset.status_code == 200
    assert reset.json() == {"message": "Password reset."}
    assert reused.status_code == 410
    assert old_session.status_code == 401
    assert new_login.status_code == 200
    assert user is not None
    assert user.password_hash is not None
    assert verify_password("NewCorrectHorse9", user.password_hash)
    assert audit_log is not None


async def test_forgot_password_rate_limits_email_and_reset_rejects_weak_password(
    client: AsyncClient,
    migrated_database: None,
    reset_test_context: dict[str, Any],
) -> None:
    """Forgot-password enforces email limits and reset validates new password."""
    await create_verified_user("limited-reset@auracles.space", "CorrectHorse9")

    for _attempt in range(3):
        response = await client.post(
            "/v1/auth/forgot-password",
            json={"email": "limited-reset@auracles.space"},
        )
        assert response.status_code == 200

    limited = await client.post(
        "/v1/auth/forgot-password",
        json={"email": "limited-reset@auracles.space"},
    )
    token = reset_test_context["sent_emails"].reset_calls[0]["token"]
    weak_password = await client.post(
        "/v1/auth/reset-password",
        json={"token": token, "new_password": "short9"},
    )

    assert limited.status_code == 429
    assert weak_password.status_code == 422


async def test_new_device_login_notification_is_sent_once_per_fingerprint(
    client: AsyncClient,
    migrated_database: None,
    reset_test_context: dict[str, Any],
) -> None:
    """New-device notifications fire once per coarse IP/User-Agent fingerprint."""
    await create_verified_user("device@auracles.space", "CorrectHorse9")

    first = await client.post(
        "/v1/auth/login",
        json={"email": "device@auracles.space", "password": "CorrectHorse9"},
        headers={"User-Agent": "Browser A"},
    )
    same_device = await client.post(
        "/v1/auth/login",
        json={"email": "device@auracles.space", "password": "CorrectHorse9"},
        headers={"User-Agent": "Browser A"},
    )
    new_agent = await client.post(
        "/v1/auth/login",
        json={"email": "device@auracles.space", "password": "CorrectHorse9"},
        headers={"User-Agent": "Browser B"},
    )

    async with async_session_factory() as session:
        audit_logs = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "new_device_login")
            )
        ).scalars().all()

    sent_emails = reset_test_context["sent_emails"]

    assert first.status_code == 200
    assert same_device.status_code == 200
    assert new_agent.status_code == 200
    assert len(sent_emails.device_calls) == 2
    assert sent_emails.device_calls[0]["email"] == "device@auracles.space"
    assert sent_emails.device_calls[0]["user_agent"] == "Browser A"
    assert sent_emails.device_calls[1]["user_agent"] == "Browser B"
    assert len(audit_logs) == 2
