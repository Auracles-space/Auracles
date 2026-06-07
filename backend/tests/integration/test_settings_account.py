"""Integration tests for account settings session and identity endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
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
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.settings import service as settings_service
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for settings session and token flows."""

    def __init__(self) -> None:
        """Create empty in-memory Redis state."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}
        self.sets: dict[str, set[str]] = {}

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a string value with a TTL."""
        self.values[key] = value
        self.ttls[key] = seconds

    async def get(self, key: str) -> str | None:
        """Return a string value or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def delete(self, *keys: str) -> int:
        """Delete string and set keys."""
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.sets)
            self.values.pop(key, None)
            self.ttls.pop(key, None)
            self.sets.pop(key, None)
        return removed

    async def incr(self, key: str) -> int:
        """Increment a counter and return it."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """Record a TTL for a key."""
        self.ttls[key] = seconds

    async def ttl(self, key: str) -> int:
        """Return a recorded TTL or Redis' no-expiry sentinel."""
        return self.ttls.get(key, -1)

    async def sadd(self, key: str, *values: str) -> int:
        """Add members to a Redis set."""
        existing = self.sets.setdefault(key, set())
        before = len(existing)
        existing.update(values)
        return len(existing) - before

    async def srem(self, key: str, *values: str) -> int:
        """Remove members from a Redis set."""
        existing = self.sets.setdefault(key, set())
        before = len(existing)
        existing.difference_update(values)
        return before - len(existing)

    async def smembers(self, key: str) -> set[str]:
        """Return set members."""
        return set(self.sets.get(key, set()))


class FakeEmailChangeTask:
    """Celery-task-shaped test double for email-change notifications."""

    def __init__(self, sent: list[tuple[str, str]]) -> None:
        """Store the list that captures task calls."""
        self.sent = sent

    def delay(self, email: str, token: str) -> None:
        """Capture delayed email-change dispatch."""
        self.sent.append((email, token))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure settings tables exist for account tests."""
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
async def settings_account_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset auth state and install fake Redis/email hooks."""
    fake_redis = FakeRedis()
    sent_email_changes: list[tuple[str, str]] = []

    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()

    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr(
        settings_service,
        "send_email_change_verification",
        FakeEmailChangeTask(sent_email_changes),
        raising=False,
    )
    try:
        yield {"redis": fake_redis, "sent_email_changes": sent_email_changes}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await engine.dispose()


async def create_verified_user(
    email: str,
    password: str,
    *,
    enable_totp: bool = False,
) -> tuple[UUID, str | None]:
    """Create a verified operator user and optional TOTP secret."""
    secret = pyotp.random_base32() if enable_totp else None
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password(password),
                display_name="Settings User",
                email_verified=True,
                totp_enabled=enable_totp,
                totp_secret=encrypt_totp_secret(secret) if secret else None,
            )
            session.add(user)
            await session.flush()
            session.add(UserRole(user_id=user.id, role="operator"))
        return user.id, secret


async def login_user(
    client: AsyncClient,
    email: str,
    password: str,
) -> tuple[str, str]:
    """Login and return access plus refresh tokens."""
    response = await client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return response.json()["access_token"], response.cookies["refresh_token"]


async def test_sessions_list_marks_current_and_can_revoke_current_refresh(
    client: AsyncClient,
    migrated_database: None,
    settings_account_context: dict[str, Any],
) -> None:
    """Session list exposes only own sessions and current session revocation works."""
    await create_verified_user("sessions@auracles.space", "CorrectHorse9")
    first_access, first_refresh = await login_user(
        client,
        "sessions@auracles.space",
        "CorrectHorse9",
    )
    await login_user(client, "sessions@auracles.space", "CorrectHorse9")

    client.cookies.set("refresh_token", first_refresh)
    listed = await client.get(
        "/v1/settings/sessions",
        headers={"Authorization": f"Bearer {first_access}"},
    )
    current_session = next(
        item for item in listed.json()["sessions"] if item["current"]
    )
    revoked = await client.delete(
        f"/v1/settings/sessions/{current_session['id']}",
        headers={"Authorization": f"Bearer {first_access}"},
    )
    refreshed_after_revoke = await client.post("/v1/auth/refresh")

    assert listed.status_code == 200
    assert len(listed.json()["sessions"]) == 2
    assert revoked.status_code == 200
    assert refreshed_after_revoke.status_code == 401


async def test_email_change_requires_totp_and_confirmation_swaps_email(
    client: AsyncClient,
    migrated_database: None,
    settings_account_context: dict[str, Any],
) -> None:
    """Email change keeps the old email until a new-address token is confirmed."""
    user_id, totp_secret = await create_verified_user(
        "email-change@auracles.space",
        "CorrectHorse9",
        enable_totp=True,
    )
    access_token = create_access_token(user_id=user_id, roles=["operator"])
    code = pyotp.TOTP(totp_secret).now()

    missing_totp = await client.post(
        "/v1/settings/account/email-change",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"new_email": "next@auracles.space"},
    )
    requested = await client.post(
        "/v1/settings/account/email-change",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"new_email": "next@auracles.space", "totp_code": code},
    )
    sent = settings_account_context["sent_email_changes"]
    confirmed = await client.post(
        "/v1/settings/account/email-change/confirm",
        json={"token": sent[0][1]},
    )
    reused = await client.post(
        "/v1/settings/account/email-change/confirm",
        json={"token": sent[0][1]},
    )

    async with async_session_factory() as session:
        user = await session.scalar(select(User).where(User.id == user_id))
        audit_log = await session.scalar(
            select(AuditLog).where(AuditLog.action == "email_changed")
        )

    assert missing_totp.status_code == 403
    assert requested.status_code == 200
    assert sent[0][0] == "next@auracles.space"
    assert confirmed.status_code == 200
    assert reused.status_code == 410
    assert user is not None
    assert user.email == "next@auracles.space"
    assert audit_log is not None


async def test_deactivate_revokes_sessions_and_blocks_future_login(
    client: AsyncClient,
    migrated_database: None,
    settings_account_context: dict[str, Any],
) -> None:
    """Deactivation requires the password, revokes sessions, and blocks login."""
    user_id, _secret = await create_verified_user(
        "deactivate@auracles.space",
        "CorrectHorse9",
    )
    access_token, refresh_token = await login_user(
        client,
        "deactivate@auracles.space",
        "CorrectHorse9",
    )

    wrong_password = await client.post(
        "/v1/settings/account/deactivate",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"password": "WrongPassword9"},
    )
    deactivated = await client.post(
        "/v1/settings/account/deactivate",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"password": "CorrectHorse9"},
    )
    client.cookies.set("refresh_token", refresh_token)
    refresh_after_deactivate = await client.post("/v1/auth/refresh")
    login_after_deactivate = await client.post(
        "/v1/auth/login",
        json={"email": "deactivate@auracles.space", "password": "CorrectHorse9"},
    )

    async with async_session_factory() as session:
        user = await session.scalar(select(User).where(User.id == user_id))
        audit_log = await session.scalar(
            select(AuditLog).where(AuditLog.action == "account_deactivated")
        )

    assert wrong_password.status_code == 401
    assert deactivated.status_code == 200
    assert deactivated.cookies.get("refresh_token") is None
    assert refresh_after_deactivate.status_code == 401
    assert login_after_deactivate.status_code == 403
    assert user is not None
    assert user.deactivated_at is not None
    assert audit_log is not None
