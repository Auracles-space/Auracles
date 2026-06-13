"""Integration tests for admin user suspension and enforcement.

These tests exercise the public admin HTTP contract for suspending and
unsuspending users, plus the auth-session behaviors that must change when a
user is blocked or restored.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.auth import service as auth_service
from app.modules.auth.models import User, UserRole
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for TOTP counters and refresh-session storage."""

    def __init__(self) -> None:
        """Create empty in-memory Redis-like state."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}
        self.sets: dict[str, set[str]] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored string or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        """Store a string value, optionally respecting NX semantics."""
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a string value with a TTL."""
        self.values[key] = value
        self.ttls[key] = seconds

    async def delete(self, *keys: str) -> int:
        """Delete string, counter, and set keys."""
        removed = 0
        for key in keys:
            removed += int(
                key in self.values or key in self.counters or key in self.sets
            )
            self.values.pop(key, None)
            self.counters.pop(key, None)
            self.ttls.pop(key, None)
            self.sets.pop(key, None)
        return removed

    async def incr(self, key: str) -> int:
        """Increment and return a counter value."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """Record a TTL assignment."""
        self.ttls[key] = seconds

    async def ttl(self, key: str) -> int:
        """Return a stored TTL or Redis' no-expiry sentinel."""
        return self.ttls.get(key, -1)

    async def sadd(self, key: str, *values: str) -> int:
        """Add one or more values to a Redis set."""
        existing = self.sets.setdefault(key, set())
        before = len(existing)
        existing.update(values)
        return len(existing) - before

    async def srem(self, key: str, *values: str) -> int:
        """Remove one or more values from a Redis set."""
        existing = self.sets.setdefault(key, set())
        before = len(existing)
        existing.difference_update(values)
        return before - len(existing)

    async def smembers(self, key: str) -> set[str]:
        """Return the members of a Redis set."""
        return set(self.sets.get(key, set()))


async def _reset_admin_user_suspension_state() -> None:
    """Delete auth and audit rows created by suspension tests."""
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the database schema is current for suspension tests."""
    backend_dir = Path(__file__).resolve().parents[2]
    sync_engine = create_engine(app.state.settings.sync_database_url)
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    command.upgrade(config, "head")
    try:
        yield
    finally:
        command.upgrade(config, "head")
        sync_engine.dispose()


@pytest.fixture
async def admin_user_suspension_context() -> AsyncIterator[FakeRedis]:
    """Reset auth state and install a Redis test double."""
    fake_redis = FakeRedis()
    await engine.dispose()
    await _reset_admin_user_suspension_state()

    async def override_redis() -> FakeRedis:
        """Return the Redis test double for dependency injection."""
        return fake_redis

    app.dependency_overrides[get_redis] = override_redis
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await _reset_admin_user_suspension_state()
        await engine.dispose()


async def _create_user(
    *,
    email: str,
    roles: list[str],
    enable_totp: bool = False,
) -> tuple[UUID, str | None]:
    """Create one verified user with approved roles and optional TOTP."""
    totp_secret = pyotp.random_base32() if enable_totp else None
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status="verified",
                totp_enabled=enable_totp,
                totp_secret=(
                    encrypt_totp_secret(totp_secret)
                    if totp_secret is not None
                    else None
                ),
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
        return user.id, totp_secret


def _auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for one test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_admin_can_suspend_and_unsuspend_user_and_force_fresh_login(
    client: AsyncClient,
    migrated_database: None,
    admin_user_suspension_context: FakeRedis,
) -> None:
    """Suspension blocks auth paths, and unsuspension invalidates old access."""
    del migrated_database
    admin_email = f"admin-suspend-{uuid4()}@auracles.space"
    user_email = f"operator-suspend-{uuid4()}@auracles.space"
    admin_id, admin_totp_secret = await _create_user(
        email=admin_email,
        roles=["admin"],
        enable_totp=True,
    )
    user_id, _ = await _create_user(
        email=user_email,
        roles=["operator"],
    )
    assert admin_totp_secret is not None

    access_token = create_access_token(user_id=user_id, roles=["operator"])
    refresh_token = "refresh-token-suspend-test"
    await auth_service._store_refresh_token(  # noqa: SLF001
        admin_user_suspension_context,
        refresh_token,
        user_id,
        family_id=str(uuid4()),
        ip="127.0.0.1",
        ua="pytest",
        totp_verified=False,
    )

    suspend = await client.post(
        f"/v1/admin/users/{user_id}/suspend",
        headers=_auth_headers(admin_id, ["admin"]),
        json={
            "reason": "Fraud investigation hold.",
            "totp_code": pyotp.TOTP(admin_totp_secret).now(),
        },
    )

    assert suspend.status_code == 200

    me_while_suspended = await client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    login_while_suspended = await client.post(
        "/v1/auth/login",
        json={
            "email": user_email,
            "password": "CorrectHorse9",
        },
    )
    client.cookies.set("refresh_token", refresh_token)
    refresh_while_suspended = await client.post("/v1/auth/refresh")

    assert me_while_suspended.status_code == 403
    assert login_while_suspended.status_code == 403
    assert refresh_while_suspended.status_code == 401

    unsuspend = await client.post(
        f"/v1/admin/users/{user_id}/unsuspend",
        headers=_auth_headers(admin_id, ["admin"]),
        json={"totp_code": pyotp.TOTP(admin_totp_secret).now()},
    )

    assert unsuspend.status_code == 200

    stale_access_after_unsuspend = await client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    fresh_login = await client.post(
        "/v1/auth/login",
        json={"email": user_email, "password": "CorrectHorse9"},
    )

    assert stale_access_after_unsuspend.status_code == 401
    assert fresh_login.status_code == 200
    assert fresh_login.json()["access_token"]


async def test_suspended_user_cannot_complete_totp_login_challenge(
    client: AsyncClient,
    migrated_database: None,
    admin_user_suspension_context: FakeRedis,
) -> None:
    """Suspended users cannot finish the TOTP challenge after password auth."""
    del migrated_database
    admin_id, admin_totp_secret = await _create_user(
        email=f"admin-2fa-suspend-{uuid4()}@auracles.space",
        roles=["admin"],
        enable_totp=True,
    )
    user_email = f"operator-2fa-suspend-{uuid4()}@auracles.space"
    user_id, user_totp_secret = await _create_user(
        email=user_email,
        roles=["operator"],
        enable_totp=True,
    )
    assert admin_totp_secret is not None
    assert user_totp_secret is not None

    login = await client.post(
        "/v1/auth/login",
        json={"email": user_email, "password": "CorrectHorse9"},
    )
    assert login.status_code == 200
    challenge_token = login.json()["challenge_token"]

    suspend = await client.post(
        f"/v1/admin/users/{user_id}/suspend",
        headers=_auth_headers(admin_id, ["admin"]),
        json={
            "reason": "Escalated account review.",
            "totp_code": pyotp.TOTP(admin_totp_secret).now(),
        },
    )
    assert suspend.status_code == 200

    verify = await client.post(
        "/v1/auth/2fa/verify-login",
        json={
            "challenge_token": challenge_token,
            "code": pyotp.TOTP(user_totp_secret).now(),
        },
    )

    assert verify.status_code == 403


async def test_admin_cannot_suspend_self(
    client: AsyncClient,
    migrated_database: None,
    admin_user_suspension_context: FakeRedis,
) -> None:
    """Admin guardrails block self-suspension requests."""
    del migrated_database, admin_user_suspension_context
    admin_id, admin_totp_secret = await _create_user(
        email=f"final-admin-{uuid4()}@auracles.space",
        roles=["admin"],
        enable_totp=True,
    )
    assert admin_totp_secret is not None

    self_suspend = await client.post(
        f"/v1/admin/users/{admin_id}/suspend",
        headers=_auth_headers(admin_id, ["admin"]),
        json={
            "reason": "Impossible request.",
            "totp_code": pyotp.TOTP(admin_totp_secret).now(),
        },
    )
    assert self_suspend.status_code == 409
