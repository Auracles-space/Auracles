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


def set_cookie_headers(response: Any) -> list[str]:
    """Return all Set-Cookie headers from an HTTPX response."""
    return response.headers.get_list("set-cookie")


def cookie_header(response: Any, cookie_name: str) -> str:
    """Return the Set-Cookie header for a specific cookie."""
    return next(
        header
        for header in set_cookie_headers(response)
        if header.startswith(f"{cookie_name}=")
    )


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
    assert response.cookies.get("session_hint") is not None
    assert "HttpOnly" in cookie_header(response, "refresh_token")
    assert "HttpOnly" not in cookie_header(response, "session_hint")
    assert len(response.cookies["session_hint"].split(".")) == 2

    me_response = await client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )

    assert me_response.status_code == 200
    assert me_response.json()["id"] == str(user_id)
    assert me_response.json()["avatar_url"] is None


async def test_me_exposes_pending_attestor_role(
    client: AsyncClient,
    migrated_database: None,
    session_test_context: dict[str, Any],
) -> None:
    """`/me` reports an unapproved attestor role under ``pending_roles``.

    A registered attestor's role is inert until admin approval, so it is excluded
    from active ``roles`` but surfaced in ``pending_roles`` so the UI can prompt
    the user to complete (or track) their attestor application.
    """

    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email="pending-attestor@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Pending Attestor",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(user_id=user.id, role="attestor", approved_at=None)
            )

    login = await client.post(
        "/v1/auth/login",
        json={"email": "pending-attestor@auracles.space", "password": "CorrectHorse9"},
    )
    access_token = login.json()["access_token"]
    me_response = await client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    body = me_response.json()
    assert me_response.status_code == 200
    assert body["roles"] == []
    assert body["pending_roles"] == ["attestor"]


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
    old_hint = login.cookies["session_hint"]

    client.cookies.set("refresh_token", old_refresh)
    refreshed = await client.post("/v1/auth/refresh")
    new_refresh = refreshed.cookies["refresh_token"]
    new_hint = refreshed.cookies["session_hint"]
    client.cookies.set("refresh_token", old_refresh)
    reused = await client.post("/v1/auth/refresh")
    client.cookies.set("refresh_token", new_refresh)
    logout = await client.post("/v1/auth/logout")
    client.cookies.set("refresh_token", new_refresh)
    after_logout = await client.post("/v1/auth/refresh")

    assert refreshed.status_code == 200
    assert new_refresh != old_refresh
    assert new_hint != old_hint
    assert reused.status_code == 401
    assert logout.status_code == 200
    assert logout.cookies.get("session_hint") is None
    assert after_logout.status_code == 401


async def test_refresh_token_reuse_writes_audit_row(
    client: AsyncClient,
    migrated_database: None,
    session_test_context: dict[str, Any],
) -> None:
    """Replaying a rotated refresh token must persist a critical audit row.

    Phase 1 Slice 4: `refresh_token_reuse_detected` is the token-theft signal.
    Family revocation is not enough — the security event has to land in
    `audit_logs` for SIEM + compliance + forensic investigation.
    """
    from sqlalchemy import select

    user_id = await create_user("reuse-audit@auracles.space", "CorrectHorse9")

    login = await client.post(
        "/v1/auth/login",
        json={"email": "reuse-audit@auracles.space", "password": "CorrectHorse9"},
    )
    old_refresh = login.cookies["refresh_token"]

    client.cookies.set("refresh_token", old_refresh)
    rotated = await client.post("/v1/auth/refresh")
    assert rotated.status_code == 200

    client.cookies.set("refresh_token", old_refresh)
    reused = await client.post("/v1/auth/refresh")

    assert reused.status_code == 401

    async with async_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "refresh_token_reuse_detected"
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    audit_row = rows[0]
    assert audit_row.actor_id == user_id
    assert audit_row.target_type == "user"
    metadata = audit_row.metadata_
    assert metadata.get("family_revoked") is True
    assert "family_id" in metadata
    assert "token_key_suffix" in metadata


async def test_refresh_token_reuse_after_full_revoke_writes_system_audit(
    client: AsyncClient,
    migrated_database: None,
    session_test_context: dict[str, Any],
) -> None:
    """When no family member survives, audit row falls back to NULL actor.

    Replay after the entire family has already been revoked is still a
    security event — it must be logged, even if the user cannot be resolved
    from Redis state. Verifies the NULL-actor fallback path.
    """
    from sqlalchemy import select

    await create_user("orphan-audit@auracles.space", "CorrectHorse9")

    login = await client.post(
        "/v1/auth/login",
        json={"email": "orphan-audit@auracles.space", "password": "CorrectHorse9"},
    )
    old_refresh = login.cookies["refresh_token"]

    client.cookies.set("refresh_token", old_refresh)
    rotated = await client.post("/v1/auth/refresh")
    assert rotated.status_code == 200
    new_refresh = rotated.cookies["refresh_token"]

    client.cookies.set("refresh_token", new_refresh)
    logout = await client.post("/v1/auth/logout")
    assert logout.status_code == 200

    client.cookies.set("refresh_token", old_refresh)
    reused = await client.post("/v1/auth/refresh")
    assert reused.status_code == 401

    async with async_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "refresh_token_reuse_detected"
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    audit_row = rows[0]
    assert audit_row.target_type == "system"
    assert audit_row.metadata_.get("family_revoked") is True


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
