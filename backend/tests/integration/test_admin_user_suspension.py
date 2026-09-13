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
from sqlalchemy import create_engine, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.auth import service as auth_service
from app.modules.auth.models import User, UserRole
from tests.conftest import open_step_up_window
from tests.support.db_cleanup import clear_identity_state_async


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
        await clear_identity_state_async(session)
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
    is_superadmin: bool = False,
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
                is_superadmin=is_superadmin,
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
    await open_step_up_window(admin_user_suspension_context, admin_id)

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
        json={"reason": "Fraud investigation hold."},
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
        json={},
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
    await open_step_up_window(admin_user_suspension_context, admin_id)

    login = await client.post(
        "/v1/auth/login",
        json={"email": user_email, "password": "CorrectHorse9"},
    )
    assert login.status_code == 200
    challenge_token = login.json()["challenge_token"]

    suspend = await client.post(
        f"/v1/admin/users/{user_id}/suspend",
        headers=_auth_headers(admin_id, ["admin"]),
        json={"reason": "Escalated account review."},
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
    del migrated_database
    admin_id, admin_totp_secret = await _create_user(
        email=f"final-admin-{uuid4()}@auracles.space",
        roles=["admin"],
        enable_totp=True,
    )
    assert admin_totp_secret is not None
    await open_step_up_window(admin_user_suspension_context, admin_id)

    self_suspend = await client.post(
        f"/v1/admin/users/{admin_id}/suspend",
        headers=_auth_headers(admin_id, ["admin"]),
        json={"reason": "Impossible request."},
    )
    assert self_suspend.status_code == 409


async def test_super_admin_cannot_be_suspended(
    client: AsyncClient,
    migrated_database: None,
    admin_user_suspension_context: FakeRedis,
) -> None:
    """No admin may suspend the protected super-admin account."""
    del migrated_database
    actor_id, actor_totp = await _create_user(
        email=f"actor-admin-{uuid4()}@auracles.space",
        roles=["admin"],
        enable_totp=True,
    )
    assert actor_totp is not None
    await open_step_up_window(admin_user_suspension_context, actor_id)
    super_id, _ = await _create_user(
        email=f"super-admin-{uuid4()}@auracles.space",
        roles=["admin"],
        is_superadmin=True,
    )

    blocked = await client.post(
        f"/v1/admin/users/{super_id}/suspend",
        headers=_auth_headers(actor_id, ["admin"]),
        json={"reason": "Attempt to suspend the super-admin."},
    )
    assert blocked.status_code == 403


async def test_non_superadmin_cannot_assign_admin_role_even_with_step_up(
    client: AsyncClient,
    migrated_database: None,
    admin_user_suspension_context: FakeRedis,
) -> None:
    """Minting a new admin is reserved for the super-admin (H1).

    A plain admin with an open step-up window must not be able to promote an
    account to admin — otherwise a single compromised admin could seed replacements and
    revoking them would be futile.
    """
    del migrated_database
    admin_id, admin_totp = await _create_user(
        email=f"plain-admin-{uuid4()}@auracles.space",
        roles=["admin"],
        enable_totp=True,
        is_superadmin=False,
    )
    target_id, _ = await _create_user(
        email=f"target-{uuid4()}@auracles.space",
        roles=["operator"],
    )
    assert admin_totp is not None
    await open_step_up_window(admin_user_suspension_context, admin_id)

    response = await client.patch(
        f"/v1/admin/users/{target_id}/roles",
        headers=_auth_headers(admin_id, ["admin"]),
        json={"role": "admin"},
    )

    assert response.status_code == 403
    async with async_session_factory() as session:
        roles = (
            (
                await session.execute(
                    select(UserRole.role).where(UserRole.user_id == target_id)
                )
            )
            .scalars()
            .all()
        )
    assert "admin" not in roles


async def test_superadmin_can_assign_admin_role_with_step_up(
    client: AsyncClient,
    migrated_database: None,
    admin_user_suspension_context: FakeRedis,
) -> None:
    """The super-admin may promote an account to admin inside a step-up window."""
    del migrated_database
    super_id, super_totp = await _create_user(
        email=f"super-{uuid4()}@auracles.space",
        roles=["admin"],
        enable_totp=True,
        is_superadmin=True,
    )
    target_id, _ = await _create_user(
        email=f"promote-{uuid4()}@auracles.space",
        roles=["operator"],
    )
    assert super_totp is not None
    await open_step_up_window(admin_user_suspension_context, super_id)

    response = await client.patch(
        f"/v1/admin/users/{target_id}/roles",
        headers=_auth_headers(super_id, ["admin"]),
        json={"role": "admin"},
    )

    assert response.status_code == 200
    async with async_session_factory() as session:
        roles = (
            (
                await session.execute(
                    select(UserRole.role).where(UserRole.user_id == target_id)
                )
            )
            .scalars()
            .all()
        )
    assert "admin" in roles


async def test_role_assignment_requires_step_up(
    client: AsyncClient,
    migrated_database: None,
    admin_user_suspension_context: FakeRedis,
) -> None:
    """Assigning any role is a sensitive write and needs an open step-up window."""
    del migrated_database
    admin_id, _ = await _create_user(
        email=f"admin-no2fa-{uuid4()}@auracles.space",
        roles=["admin"],
        enable_totp=True,
    )
    target_id, _ = await _create_user(
        email=f"target-no2fa-{uuid4()}@auracles.space",
        roles=["operator"],
    )

    response = await client.patch(
        f"/v1/admin/users/{target_id}/roles",
        headers=_auth_headers(admin_id, ["admin"]),
        json={"role": "attestor"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "step_up_required"
    async with async_session_factory() as session:
        approved = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == target_id, UserRole.role == "attestor"
            )
        )
    assert approved is None


async def test_kyc_override_requires_step_up(
    client: AsyncClient,
    migrated_database: None,
    admin_user_suspension_context: FakeRedis,
) -> None:
    """Marking an account KYC-verified unlocks payouts, so it needs step-up."""
    del migrated_database
    admin_id, admin_totp = await _create_user(
        email=f"kyc-admin-{uuid4()}@auracles.space",
        roles=["admin"],
        enable_totp=True,
    )
    target_id, _ = await _create_user(
        email=f"kyc-target-{uuid4()}@auracles.space",
        roles=["contributor"],
    )
    assert admin_totp is not None
    async with async_session_factory() as session:
        async with session.begin():
            target = await session.get(User, target_id)
            assert target is not None
            target.kyc_status = "pending"

    rejected = await client.patch(
        f"/v1/admin/users/{target_id}/kyc",
        headers=_auth_headers(admin_id, ["admin"]),
        json={"status": "verified"},
    )
    assert rejected.status_code == 403
    assert rejected.json()["detail"]["error_code"] == "step_up_required"

    await open_step_up_window(admin_user_suspension_context, admin_id)
    accepted = await client.patch(
        f"/v1/admin/users/{target_id}/kyc",
        headers=_auth_headers(admin_id, ["admin"]),
        json={"status": "verified"},
    )
    assert accepted.status_code == 200
    async with async_session_factory() as session:
        target = await session.get(User, target_id)
        assert target is not None
        assert target.kyc_status == "verified"


async def test_step_up_window_covers_several_sensitive_actions(
    client: AsyncClient,
    migrated_database: None,
    admin_user_suspension_context: FakeRedis,
) -> None:
    """One step-up verification opens a window that spans several actions.

    The per-request TOTP code (single-use, M4) is replaced by a short-lived
    window opened once via ``POST /v1/auth/step-up``; an admin working
    through a queue must not be asked for a code on every write.
    """
    del migrated_database
    admin_id, admin_totp = await _create_user(
        email=f"replay-admin-{uuid4()}@auracles.space",
        roles=["admin"],
        enable_totp=True,
    )
    user_a, _ = await _create_user(
        email=f"replay-a-{uuid4()}@auracles.space", roles=["operator"]
    )
    user_b, _ = await _create_user(
        email=f"replay-b-{uuid4()}@auracles.space", roles=["operator"]
    )
    assert admin_totp is not None
    await open_step_up_window(admin_user_suspension_context, admin_id)

    first = await client.post(
        f"/v1/admin/users/{user_a}/suspend",
        headers=_auth_headers(admin_id, ["admin"]),
        json={"reason": "First action."},
    )
    assert first.status_code == 200

    second = await client.post(
        f"/v1/admin/users/{user_b}/suspend",
        headers=_auth_headers(admin_id, ["admin"]),
        json={"reason": "Second action in the same window."},
    )
    assert second.status_code == 200

    async with async_session_factory() as session:
        target_b = await session.get(User, user_b)
        assert target_b is not None
        assert target_b.suspended_at is not None


async def test_admin_without_2fa_is_told_to_enrol(
    client: AsyncClient,
    migrated_database: None,
    admin_user_suspension_context: FakeRedis,
) -> None:
    """An admin who never enrolled in 2FA gets ``totp_setup_required``.

    The gate cannot be satisfied without an authenticator, so the response
    points the admin at security settings instead of a dead-end 403.
    """
    del migrated_database, admin_user_suspension_context
    admin_id, _ = await _create_user(
        email=f"no-totp-admin-{uuid4()}@auracles.space",
        roles=["admin"],
    )
    target_id, _ = await _create_user(
        email=f"no-totp-target-{uuid4()}@auracles.space",
        roles=["operator"],
    )

    response = await client.post(
        f"/v1/admin/users/{target_id}/suspend",
        headers=_auth_headers(admin_id, ["admin"]),
        json={"reason": "Should be refused."},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "totp_setup_required"
    assert response.json()["detail"]["onboarding_url"] == "/settings/security"


async def test_role_assignment_revokes_targets_existing_tokens(
    client: AsyncClient,
    migrated_database: None,
    admin_user_suspension_context: FakeRedis,
) -> None:
    """A role change forces the target to refresh so it takes effect now (L5).

    Access tokens carry role claims; without a revocation bump a role change
    would not apply until the target's existing token expired (≤15 min).
    """
    del migrated_database
    super_id, super_totp = await _create_user(
        email=f"l5-super-{uuid4()}@auracles.space",
        roles=["admin"],
        enable_totp=True,
        is_superadmin=True,
    )
    target_id, _ = await _create_user(
        email=f"l5-target-{uuid4()}@auracles.space",
        roles=["operator"],
    )
    assert super_totp is not None
    await open_step_up_window(admin_user_suspension_context, super_id)
    stale_headers = _auth_headers(target_id, ["operator"])

    # The target's token works before the role change.
    before = await client.get("/v1/auth/me", headers=stale_headers)
    assert before.status_code == 200

    assigned = await client.patch(
        f"/v1/admin/users/{target_id}/roles",
        headers=_auth_headers(super_id, ["admin"]),
        json={"role": "admin"},
    )
    assert assigned.status_code == 200

    # The pre-change token is now rejected, forcing a refresh that re-derives
    # roles from the database.
    after = await client.get("/v1/auth/me", headers=stale_headers)
    assert after.status_code == 401
