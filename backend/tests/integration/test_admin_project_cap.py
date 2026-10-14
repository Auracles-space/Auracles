"""Integration tests for the admin per-account active-Project ceiling.

BR-PROJ-004 caps an Operator at five concurrent active Projects. These exercise
the admin HTTP contract that raises that ceiling for one account, including the
RBAC gate, the audit trail, and clearing the override back to the default.
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
from sqlalchemy import create_engine, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.projects.service import MAX_ACTIVE_PROJECTS
from app.shared.models.audit_log import AuditLog
from tests.conftest import open_step_up_window
from tests.support.db_cleanup import clear_identity_state_async


class FakeRedis:
    """Minimal Redis double covering the step-up window reads."""

    def __init__(self) -> None:
        """Create empty in-memory Redis-like state."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored string value."""
        return self.values.get(key)

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
        """Delete string keys."""
        removed = 0
        for key in keys:
            removed += int(key in self.values)
            self.values.pop(key, None)
            self.ttls.pop(key, None)
        return removed

    async def ttl(self, key: str) -> int:
        """Return a stored TTL or Redis' no-expiry sentinel."""
        return self.ttls.get(key, -1)


async def _reset_project_cap_state() -> None:
    """Delete the auth and audit rows these tests create."""
    async with async_session_factory() as session:
        await clear_identity_state_async(session)
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the database schema is current for project-cap tests."""
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
async def project_cap_context() -> AsyncIterator[FakeRedis]:
    """Reset auth state and install a Redis test double."""
    fake_redis = FakeRedis()
    await engine.dispose()
    await _reset_project_cap_state()

    async def override_redis() -> FakeRedis:
        """Return the Redis test double for dependency injection."""
        return fake_redis

    app.dependency_overrides[get_redis] = override_redis
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await _reset_project_cap_state()
        await engine.dispose()


async def _create_user(
    *,
    email: str,
    roles: list[str],
    enable_totp: bool = False,
) -> UUID:
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
        return user.id


def _auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for one test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_admin_raises_and_clears_one_operator_ceiling(
    client: AsyncClient,
    migrated_database: None,
    project_cap_context: FakeRedis,
) -> None:
    """An admin can raise one account's ceiling and put it back.

    Clearing is expressed as null rather than as the default number, so the
    account returns to following BR-PROJ-004 instead of being pinned to today's
    value of it.
    """
    del migrated_database
    admin_id = await _create_user(
        email=f"admin-cap-{uuid4()}@auracles.space",
        roles=["admin"],
        enable_totp=True,
    )
    operator_id = await _create_user(
        email=f"operator-cap-{uuid4()}@auracles.space",
        roles=["operator"],
    )
    await open_step_up_window(project_cap_context, admin_id)

    raised = await client.patch(
        f"/v1/admin/users/{operator_id}/project-cap",
        headers=_auth_headers(admin_id, ["admin"]),
        json={
            "max_active_projects": 25,
            "reason": "Pilot operator running the launch cohort.",
        },
    )

    assert raised.status_code == 200
    assert raised.json()["max_active_projects"] == 25
    assert raised.json()["default_max_active_projects"] == MAX_ACTIVE_PROJECTS

    async with async_session_factory() as session:
        stored = await session.get(User, operator_id)
        assert stored is not None
        assert stored.max_active_projects == 25

    cleared = await client.patch(
        f"/v1/admin/users/{operator_id}/project-cap",
        headers=_auth_headers(admin_id, ["admin"]),
        json={"max_active_projects": None, "reason": "Pilot cohort finished."},
    )

    assert cleared.status_code == 200
    assert cleared.json()["max_active_projects"] is None

    async with async_session_factory() as session:
        stored = await session.get(User, operator_id)
        assert stored is not None
        assert stored.max_active_projects is None


async def test_project_cap_change_is_audited(
    client: AsyncClient,
    migrated_database: None,
    project_cap_context: FakeRedis,
) -> None:
    """Raising a ceiling writes an audit entry naming both values.

    An admin lifting a business rule for one account is exactly the kind of
    action the audit trail exists for; the previous value is recorded so the
    change is reversible from the log alone.
    """
    del migrated_database
    admin_id = await _create_user(
        email=f"admin-cap-audit-{uuid4()}@auracles.space",
        roles=["admin"],
        enable_totp=True,
    )
    operator_id = await _create_user(
        email=f"operator-cap-audit-{uuid4()}@auracles.space",
        roles=["operator"],
    )
    await open_step_up_window(project_cap_context, admin_id)

    response = await client.patch(
        f"/v1/admin/users/{operator_id}/project-cap",
        headers=_auth_headers(admin_id, ["admin"]),
        json={
            "max_active_projects": 12,
            "reason": "Agency operator with concurrent engagements.",
        },
    )
    assert response.status_code == 200

    async with async_session_factory() as session:
        entry = await session.scalar(
            select(AuditLog).where(AuditLog.action == "project_cap_override_set")
        )
    assert entry is not None
    assert entry.actor_id == admin_id
    assert entry.target_id == operator_id
    assert entry.metadata_["previous"] is None
    assert entry.metadata_["max_active_projects"] == 12
    assert entry.metadata_["reason"] == ("Agency operator with concurrent engagements.")


async def test_project_cap_rejects_a_ceiling_below_one(
    client: AsyncClient,
    migrated_database: None,
    project_cap_context: FakeRedis,
) -> None:
    """A zero ceiling is refused at 422 rather than silently barring posting.

    Stopping an account from posting is suspension, which has its own endpoint,
    its own reason field, and its own session revocation.
    """
    del migrated_database
    admin_id = await _create_user(
        email=f"admin-cap-zero-{uuid4()}@auracles.space",
        roles=["admin"],
        enable_totp=True,
    )
    operator_id = await _create_user(
        email=f"operator-cap-zero-{uuid4()}@auracles.space",
        roles=["operator"],
    )
    await open_step_up_window(project_cap_context, admin_id)

    response = await client.patch(
        f"/v1/admin/users/{operator_id}/project-cap",
        headers=_auth_headers(admin_id, ["admin"]),
        json={"max_active_projects": 0, "reason": "Should not be accepted."},
    )

    assert response.status_code == 422


async def test_project_cap_requires_an_admin(
    client: AsyncClient,
    migrated_database: None,
    project_cap_context: FakeRedis,
) -> None:
    """A non-admin is refused, and an anonymous caller is unauthenticated."""
    del migrated_database, project_cap_context
    operator_id = await _create_user(
        email=f"operator-cap-rbac-{uuid4()}@auracles.space",
        roles=["operator"],
    )

    forbidden = await client.patch(
        f"/v1/admin/users/{operator_id}/project-cap",
        headers=_auth_headers(operator_id, ["operator"]),
        json={"max_active_projects": 50, "reason": "Raising my own ceiling."},
    )
    anonymous = await client.patch(
        f"/v1/admin/users/{operator_id}/project-cap",
        json={"max_active_projects": 50, "reason": "Raising a stranger's ceiling."},
    )

    assert forbidden.status_code == 403
    assert anonymous.status_code == 401

    async with async_session_factory() as session:
        stored = await session.get(User, operator_id)
        assert stored is not None
        assert stored.max_active_projects is None


async def test_project_cap_404s_for_an_unknown_user(
    client: AsyncClient,
    migrated_database: None,
    project_cap_context: FakeRedis,
) -> None:
    """A ceiling cannot be set on an account that does not exist."""
    del migrated_database
    admin_id = await _create_user(
        email=f"admin-cap-404-{uuid4()}@auracles.space",
        roles=["admin"],
        enable_totp=True,
    )
    await open_step_up_window(project_cap_context, admin_id)

    response = await client.patch(
        f"/v1/admin/users/{uuid4()}/project-cap",
        headers=_auth_headers(admin_id, ["admin"]),
        json={"max_active_projects": 9, "reason": "No such account."},
    )

    assert response.status_code == 404
