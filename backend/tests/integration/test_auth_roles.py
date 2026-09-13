"""Integration tests for RBAC and role assignment."""

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
    encrypt_totp_secret,
    hash_password,
)
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import PlatformConfig
from app.modules.gdpr.models import ConsentLog
from app.shared.models.audit_log import AuditLog
from tests.conftest import open_step_up_window


class FakeRedis:
    """In-memory Redis double supporting TOTP counters and lockout sets."""

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


async def _create_admin_with_totp(
    email: str,
    *,
    is_superadmin: bool = False,
) -> tuple[UUID, str]:
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
                is_superadmin=is_superadmin,
                totp_secret=encrypt_totp_secret(secret),
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(user_id=user.id, role="admin", approved_at=datetime.now(UTC))
            )
        return user.id, secret


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure auth tables exist for RBAC tests."""
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
async def role_test_context() -> AsyncIterator[dict[str, Any]]:
    """Reset auth tables and install a Redis override."""
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(ConsentLog))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        config_defaults = {
            "consent_version_terms_of_service": "1.0",
            "consent_version_privacy_policy": "1.0",
        }
        for key, value in config_defaults.items():
            config = await session.get(PlatformConfig, key)
            if config is None:
                session.add(PlatformConfig(key=key, value=value))
            else:
                config.value = value
        await session.commit()

    # One shared double: the step-up window seeded before a request must be
    # the instance the dependency reads during it.
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield {"redis": fake_redis}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await engine.dispose()


async def create_user_with_roles(email: str, roles: list[str]) -> UUID:
    """Create a verified user with approved non-attestor roles."""
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


async def record_current_consent(user_id: UUID) -> None:
    """Create current-version consent rows for role-gated test users."""
    async with async_session_factory() as session:
        async with session.begin():
            for document_type in ("terms_of_service", "privacy_policy"):
                session.add(
                    ConsentLog(
                        user_id=user_id,
                        document_type=document_type,
                        version="1.0",
                        accepted_at=datetime.now(UTC),
                    )
                )


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_user_can_self_add_contributor_or_operator_role(
    client: AsyncClient,
    migrated_database: None,
    role_test_context: dict[str, Any],
) -> None:
    """Authenticated users can self-add Contributor or Operator roles."""
    user_id = await create_user_with_roles("operator@auracles.space", ["operator"])
    await record_current_consent(user_id)

    response = await client.post(
        "/v1/auth/roles",
        json={"role": "contributor"},
        headers=auth_headers(user_id, ["operator"]),
    )

    async with async_session_factory() as session:
        roles = (
            (
                await session.execute(
                    select(UserRole.role).where(UserRole.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )

    assert response.status_code == 200
    assert set(roles) == {"operator", "contributor"}


async def test_user_cannot_self_add_attestor_and_duplicate_returns_409(
    client: AsyncClient,
    migrated_database: None,
    role_test_context: dict[str, Any],
) -> None:
    """Attestor self-add is rejected (org-derived only) and duplicates conflict."""
    user_id = await create_user_with_roles(
        "contributor@auracles.space",
        ["contributor"],
    )
    await record_current_consent(user_id)

    attestor = await client.post(
        "/v1/auth/roles",
        json={"role": "attestor"},
        headers=auth_headers(user_id, ["contributor"]),
    )
    duplicate = await client.post(
        "/v1/auth/roles",
        json={"role": "contributor"},
        headers=auth_headers(user_id, ["contributor"]),
    )

    # Attestor is no longer self-selectable — it is granted only as a derived
    # role through an organization's active attestor capability.
    assert attestor.status_code == 422
    assert duplicate.status_code == 409


async def test_self_add_role_requires_current_consent(
    client: AsyncClient,
    migrated_database: None,
    role_test_context: dict[str, Any],
) -> None:
    """Privileged self-role changes are blocked until current consent exists."""
    del migrated_database, role_test_context
    user_id = await create_user_with_roles("stale-consent@auracles.space", ["operator"])

    response = await client.post(
        "/v1/auth/roles",
        json={"role": "contributor"},
        headers=auth_headers(user_id, ["operator"]),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "consent_required"
    assert response.json()["detail"]["missing_documents"] == [
        "terms_of_service",
        "privacy_policy",
    ]


async def test_admin_can_approve_attestor_role(
    client: AsyncClient,
    migrated_database: None,
    role_test_context: dict[str, Any],
) -> None:
    """Admins can assign and approve the Attestor role for another user."""
    admin_id, _ = await _create_admin_with_totp("admin@auracles.space")
    await open_step_up_window(role_test_context["redis"], admin_id)
    target_id = await create_user_with_roles("target@auracles.space", ["operator"])

    response = await client.patch(
        f"/v1/admin/users/{target_id}/roles",
        json={"role": "attestor"},
        headers=auth_headers(admin_id, ["admin"]),
    )

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == target_id,
                UserRole.role == "attestor",
            )
        )
        audit_log = await session.scalar(
            select(AuditLog).where(AuditLog.action == "attestor_approved")
        )

    assert response.status_code == 200
    assert role is not None
    assert role.approved_at is not None
    assert role.approved_by == admin_id
    assert audit_log is not None


async def test_non_admin_admin_role_assignment_is_denied_and_audited(
    client: AsyncClient,
    migrated_database: None,
    role_test_context: dict[str, Any],
) -> None:
    """RBAC dependency denies non-admin calls and writes access_denied audit.

    The caller is enrolled in 2FA with an open step-up window, so the step-up
    gate (which runs first) passes and the 403 and audit row are the role
    gate's.
    """
    user_id = await create_user_with_roles("operator2@auracles.space", ["operator"])
    async with async_session_factory() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            assert user is not None
            user.totp_enabled = True
            user.totp_secret = encrypt_totp_secret(pyotp.random_base32())
    await open_step_up_window(role_test_context["redis"], user_id)
    target_id = await create_user_with_roles("target2@auracles.space", ["operator"])

    response = await client.patch(
        f"/v1/admin/users/{target_id}/roles",
        json={"role": "attestor"},
        headers=auth_headers(user_id, ["operator"]),
    )

    async with async_session_factory() as session:
        audit_log = await session.scalar(
            select(AuditLog).where(AuditLog.action == "access_denied")
        )

    assert response.status_code == 403
    assert audit_log is not None


async def test_admin_role_assignment_requires_token_role_claim(
    client: AsyncClient,
    migrated_database: None,
    role_test_context: dict[str, Any],
) -> None:
    """A user with DB admin role but no token admin claim is denied."""
    admin_id = await create_user_with_roles("claimless@auracles.space", ["admin"])
    target_id = await create_user_with_roles("target3@auracles.space", ["operator"])

    response = await client.patch(
        f"/v1/admin/users/{target_id}/roles",
        json={"role": "attestor"},
        headers=auth_headers(admin_id, []),
    )

    assert response.status_code == 403
