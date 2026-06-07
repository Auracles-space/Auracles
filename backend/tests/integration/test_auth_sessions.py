"""Integration tests for login, refresh, logout, and current-user auth."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for refresh tokens and rate limits."""

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
        """Return a stored string value if present."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def delete(self, *keys: str) -> int:
        """Delete one or more keys and return the number removed."""
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
        """Return set members."""
        return set(self.sets.get(key, set()))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure auth tables exist for session tests."""
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
async def session_test_context() -> AsyncIterator[dict[str, Any]]:
    """Install fake Redis and reset auth tables for session tests."""
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


async def create_user(
    email: str,
    password: str,
    *,
    verified: bool = True,
    deactivated: bool = False,
) -> UUID:
    """Create a user and operator role for auth session tests."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password(password),
                display_name="Session User",
                email_verified=verified,
            )
            if deactivated:
                from datetime import UTC, datetime

                user.deactivated_at = datetime.now(UTC)
            session.add(user)
            await session.flush()
            session.add(UserRole(user_id=user.id, role="operator"))
        return user.id


async def test_login_sets_refresh_cookie_and_me_accepts_access_token(
    client: AsyncClient,
    migrated_database: None,
    session_test_context: dict[str, Any],
) -> None:
    """Login returns access JSON only, stores refresh in cookie, and enables /me."""
    user_id = await create_user("login@auracles.space", "CorrectHorse9")

    response = await client.post(
        "/v1/auth/login",
        json={"email": "LOGIN@auracles.space", "password": "CorrectHorse9"},
    )

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"
    assert response.cookies.get("refresh_token") is not None
    assert "HttpOnly" in response.headers["set-cookie"]

    me_response = await client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )

    assert me_response.status_code == 200
    assert me_response.json()["id"] == str(user_id)


async def test_login_rejects_unverified_and_deactivated_accounts(
    client: AsyncClient,
    migrated_database: None,
    session_test_context: dict[str, Any],
) -> None:
    """Login denies unverified and deactivated accounts before issuing tokens."""
    await create_user("unverified@auracles.space", "CorrectHorse9", verified=False)
    await create_user("deactivated@auracles.space", "CorrectHorse9", deactivated=True)

    unverified = await client.post(
        "/v1/auth/login",
        json={"email": "unverified@auracles.space", "password": "CorrectHorse9"},
    )
    deactivated = await client.post(
        "/v1/auth/login",
        json={"email": "deactivated@auracles.space", "password": "CorrectHorse9"},
    )

    assert unverified.status_code == 403
    assert deactivated.status_code == 403


async def test_login_rate_limits_failed_password_attempts(
    client: AsyncClient,
    migrated_database: None,
    session_test_context: dict[str, Any],
) -> None:
    """Five failed password attempts lock the email temporarily."""
    await create_user("limited-login@auracles.space", "CorrectHorse9")

    for _attempt in range(5):
        response = await client.post(
            "/v1/auth/login",
            json={"email": "limited-login@auracles.space", "password": "WrongPass9"},
        )
        assert response.status_code == 401

    locked_response = await client.post(
        "/v1/auth/login",
        json={"email": "limited-login@auracles.space", "password": "CorrectHorse9"},
    )

    assert locked_response.status_code == 429


async def test_refresh_rotates_cookie_and_logout_revokes_session(
    client: AsyncClient,
    migrated_database: None,
    session_test_context: dict[str, Any],
) -> None:
    """Refresh rotates the cookie token, and logout clears/revokes it."""
    await create_user("refresh@auracles.space", "CorrectHorse9")
    login = await client.post(
        "/v1/auth/login",
        json={"email": "refresh@auracles.space", "password": "CorrectHorse9"},
    )
    old_refresh = login.cookies["refresh_token"]

    client.cookies.set("refresh_token", old_refresh)
    refreshed = await client.post("/v1/auth/refresh")
    new_refresh = refreshed.cookies["refresh_token"]
    client.cookies.set("refresh_token", old_refresh)
    reused = await client.post("/v1/auth/refresh")
    client.cookies.set("refresh_token", new_refresh)
    logout = await client.post("/v1/auth/logout")
    client.cookies.set("refresh_token", new_refresh)
    after_logout = await client.post("/v1/auth/refresh")

    assert refreshed.status_code == 200
    assert new_refresh != old_refresh
    assert reused.status_code == 401
    assert logout.status_code == 200
    assert after_logout.status_code == 401


async def test_cors_allows_configured_origin(client: AsyncClient) -> None:
    """CORS preflight succeeds for configured frontend origins."""
    response = await client.options(
        "/v1/auth/login",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
