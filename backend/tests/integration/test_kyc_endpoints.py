"""Integration tests for the admin identity-verification override.

Identity verification is automated via Persona; the admin PATCH endpoint is the
manual override for appeals and unresolvable cases. It sets kyc_status directly
without any uploaded document.

Maps to: identity verification design (2026-06-24), build slice 4.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import UUID

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, select

from app.core.database import async_session_factory, engine
from app.core.dependencies import require_kyc_verified
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    encrypt_totp_secret,
    hash_password,
)
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.notifications.models import Notification
from app.shared.models.audit_log import AuditLog
from tests.conftest import open_step_up_window
from tests.support.db_cleanup import clear_identity_state_async


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure identity tables exist for endpoint tests."""
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


class FakeRedis:
    """In-memory Redis double so admin TOTP verification is deterministic."""

    def __init__(self) -> None:
        """Create empty in-memory Redis-like state."""
        self.values: dict[str, str] = {}
        self.counters: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored string or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool:
        """Store a string value, optionally respecting NX semantics."""
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a string value with a TTL."""
        del seconds
        self.values[key] = value

    async def delete(self, *keys: str) -> int:
        """Delete string and counter keys."""
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.counters)
            self.values.pop(key, None)
            self.counters.pop(key, None)
        return removed

    async def incr(self, key: str) -> int:
        """Increment and return a counter value."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """No-op TTL assignment for the test double."""
        del key, seconds

    async def ttl(self, key: str) -> int:
        """Return the no-expiry sentinel."""
        del key
        return -1


@pytest.fixture
async def kyc_test_context() -> AsyncIterator[None]:
    """Reset auth/identity state and install a Redis double around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    # One shared double: the step-up window seeded before a request must be
    # the instance the dependency reads during it.
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def _open_step_up(admin_id: UUID) -> None:
    """Seed a step-up window on the Redis double installed by the fixture."""
    await open_step_up_window(app.dependency_overrides[get_redis](), admin_id)


async def _create_admin_with_totp(email: str) -> tuple[UUID, str]:
    """Create a verified admin with TOTP enabled; return its id and secret."""
    secret = pyotp.random_base32()
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                totp_enabled=True,
                totp_secret=encrypt_totp_secret(secret),
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(user_id=user.id, role="admin", approved_at=datetime.now(UTC))
            )
        return user.id, secret


async def create_user_with_roles(email: str, roles: list[str]) -> UUID:
    """Create a verified user with approved roles."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
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
        return user.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_admin_override_verifies_user_and_dependency_allows(
    client: AsyncClient,
    migrated_database: None,
    kyc_test_context: None,
) -> None:
    """Admin override sets verified without a document and satisfies the gate."""
    user_id = await create_user_with_roles("verify-kyc@auracles.space", ["operator"])
    admin_id, _ = await _create_admin_with_totp("kyc-admin@auracles.space")
    await _open_step_up(admin_id)

    response = await client.patch(
        f"/v1/admin/users/{user_id}/kyc",
        json={"status": "verified", "notes": "Appeal approved."},
        headers=auth_headers(admin_id, ["admin"]),
    )

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        audit_log = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "kyc_status_change",
                AuditLog.actor_id == admin_id,
            )
        )
        allowed_user = await require_kyc_verified(user)  # type: ignore[arg-type]

    assert response.status_code == 200
    assert response.json()["kyc_status"] == "verified"
    assert user is not None and user.kyc_status == "verified"
    assert audit_log is not None
    assert allowed_user.id == user_id


async def test_admin_override_notifies_reviewed_user(
    client: AsyncClient,
    migrated_database: None,
    kyc_test_context: None,
) -> None:
    """An override creates a durable in-app notification for the user."""
    user_id = await create_user_with_roles("notify-kyc@auracles.space", ["operator"])
    admin_id, _ = await _create_admin_with_totp("kyc-admin2@auracles.space")
    await _open_step_up(admin_id)

    response = await client.patch(
        f"/v1/admin/users/{user_id}/kyc",
        json={"status": "verified", "notes": "Reviewed."},
        headers=auth_headers(admin_id, ["admin"]),
    )

    async with async_session_factory() as session:
        notification = await session.scalar(
            select(Notification).where(Notification.user_id == user_id)
        )

    assert response.status_code == 200
    assert notification is not None
    assert notification.notification_type == "kyc_verified"
    assert notification.link == "/settings/kyc"


async def test_admin_override_requires_existing_user(
    client: AsyncClient,
    migrated_database: None,
    kyc_test_context: None,
) -> None:
    """Overriding a non-existent user returns 404."""
    admin_id, _ = await _create_admin_with_totp("kyc-admin3@auracles.space")
    await _open_step_up(admin_id)

    response = await client.patch(
        f"/v1/admin/users/{UUID(int=0)}/kyc",
        json={"status": "verified"},
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert response.status_code == 404
