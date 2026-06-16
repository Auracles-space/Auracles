"""Integration tests for Phase 1 auth registration flows."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.main import app
from app.modules.auth import service as auth_service
from app.modules.auth.models import User, UserRole
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for auth token and rate-limit flows."""

    def __init__(self) -> None:
        """Create empty in-memory Redis storage."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a value with a TTL."""
        self.values[key] = value
        self.ttls[key] = seconds

    async def get(self, key: str) -> str | None:
        """Return a stored value if present."""
        return self.values.get(key)

    async def delete(self, key: str) -> int:
        """Delete a key and return whether it existed."""
        existed = key in self.values
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return int(existed)

    async def incr(self, key: str) -> int:
        """Increment and return a rate-limit counter."""
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """Record a TTL for token or rate-limit keys."""
        self.ttls[key] = seconds

    async def ttl(self, key: str) -> int:
        """Return the TTL for a key or Redis' no-expiry sentinel."""
        return self.ttls.get(key, -1)


class SentVerificationEmails:
    """Capture verification email task dispatches."""

    def __init__(self) -> None:
        """Create an empty task dispatch recorder."""
        self.calls: list[dict[str, str]] = []

    def delay(self, email: str, token: str) -> None:
        """Record a Celery-style async task dispatch."""
        self.calls.append({"email": email, "token": token})


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure auth tables exist and clear auth rows before each test."""
    engine = create_engine(app.state.settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


@pytest.fixture
async def auth_test_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Install fake Redis and task dispatch hooks for auth endpoint tests."""
    fake_redis = FakeRedis()
    sent_emails = SentVerificationEmails()

    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()

    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr(auth_service, "send_verification_email", sent_emails)
    try:
        yield {"redis": fake_redis, "sent_emails": sent_emails}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await engine.dispose()


async def test_register_creates_user_roles_verification_token_and_audit(
    client: AsyncClient,
    migrated_database: None,
    auth_test_context: dict[str, Any],
) -> None:
    """Registration creates a pending identity and dispatches verification email."""
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": "NewUser@Auracles.Space ",
            "password": "CorrectHorse9",
            "display_name": "New User",
            "roles": ["contributor", "operator"],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"message": "If email is new, verification sent."}

    async with async_session_factory() as session:
        user = await session.scalar(
            select(User).where(User.email == "newuser@auracles.space")
        )
        roles = (
            await session.execute(
                select(UserRole.role, UserRole.approved_at).where(
                    UserRole.user_id == user.id
                )
            )
        ).all()
        audit_log = await session.scalar(
            select(AuditLog).where(AuditLog.action == "register_success")
        )

    sent_emails = auth_test_context["sent_emails"]
    fake_redis = auth_test_context["redis"]

    assert user is not None
    assert user.email_verified is False
    assert {role for role, _approved_at in roles} == {"contributor", "operator"}
    assert sent_emails.calls == [
        {"email": "newuser@auracles.space", "token": sent_emails.calls[0]["token"]}
    ]
    assert sent_emails.calls[0]["token"].startswith("ev_")
    assert set(fake_redis.ttls.values()) == {86_400}
    assert audit_log is not None


async def test_register_attestor_alone_creates_unapproved_role(
    client: AsyncClient,
    migrated_database: None,
    auth_test_context: dict[str, Any],
) -> None:
    """Attestor registers standalone and the role persists pending admin approval.

    Attestor cannot be combined with other roles at registration, and the role
    is created unapproved (approved_at is None) until an admin grants it.
    """
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": "attestor@auracles.space",
            "password": "CorrectHorse9",
            "display_name": "Sole Attestor",
            "roles": ["attestor"],
        },
    )

    assert response.status_code == 200

    async with async_session_factory() as session:
        user = await session.scalar(
            select(User).where(User.email == "attestor@auracles.space")
        )
        roles = (
            await session.execute(
                select(UserRole.role, UserRole.approved_at).where(
                    UserRole.user_id == user.id
                )
            )
        ).all()

    assert {role for role, _approved_at in roles} == {"attestor"}
    assert all(approved_at is None for _role, approved_at in roles)


async def test_register_rejects_attestor_combined_with_other_roles(
    client: AsyncClient,
    migrated_database: None,
    auth_test_context: dict[str, Any],
) -> None:
    """Combining attestor with another role at registration is rejected (422)."""
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": "combo@auracles.space",
            "password": "CorrectHorse9",
            "display_name": "Combo User",
            "roles": ["attestor", "operator"],
        },
    )

    assert response.status_code == 422


async def test_duplicate_register_returns_generic_success_without_second_user(
    client: AsyncClient,
    migrated_database: None,
    auth_test_context: dict[str, Any],
) -> None:
    """Duplicate registration uses the no-enumeration response and logs an audit."""
    payload = {
        "email": "duplicate@auracles.space",
        "password": "CorrectHorse9",
        "display_name": "Duplicate User",
        "roles": ["operator"],
    }

    first_response = await client.post("/v1/auth/register", json=payload)
    second_response = await client.post("/v1/auth/register", json=payload)

    async with async_session_factory() as session:
        users = (
            await session.execute(select(User).where(User.email == payload["email"]))
        ).scalars().all()
        duplicate_audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "register_duplicate_attempt")
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json() == {"message": "If email is new, verification sent."}
    assert len(users) == 1
    assert duplicate_audit is not None


async def test_verify_email_marks_user_verified_and_consumes_token(
    client: AsyncClient,
    migrated_database: None,
    auth_test_context: dict[str, Any],
) -> None:
    """Email verification marks the user verified and makes the token single-use."""
    await client.post(
        "/v1/auth/register",
        json={
            "email": "verify@auracles.space",
            "password": "CorrectHorse9",
            "display_name": "Verify User",
            "roles": ["contributor"],
        },
    )
    token = auth_test_context["sent_emails"].calls[0]["token"]

    response = await client.post("/v1/auth/verify-email", json={"token": token})
    reused_response = await client.post("/v1/auth/verify-email", json={"token": token})

    async with async_session_factory() as session:
        user = await session.scalar(
            select(User).where(User.email == "verify@auracles.space")
        )
        audit_log = await session.scalar(
            select(AuditLog).where(AuditLog.action == "email_verified")
        )

    assert response.status_code == 200
    assert response.json() == {"message": "Email verified."}
    assert reused_response.status_code == 410
    assert user is not None
    assert user.email_verified is True
    assert audit_log is not None


async def test_verify_email_rejects_malformed_token(
    client: AsyncClient,
    migrated_database: None,
    auth_test_context: dict[str, Any],
) -> None:
    """Malformed verification tokens return 400 before Redis lookup."""
    response = await client.post("/v1/auth/verify-email", json={"token": "not-a-token"})

    assert response.status_code == 400


async def test_resend_verification_sends_new_token_for_unverified_user(
    client: AsyncClient,
    migrated_database: None,
    auth_test_context: dict[str, Any],
) -> None:
    """Resend verification queues a new token for an existing unverified user."""
    await client.post(
        "/v1/auth/register",
        json={
            "email": "resend@auracles.space",
            "password": "CorrectHorse9",
            "display_name": "Resend User",
            "roles": ["operator"],
        },
    )

    response = await client.post(
        "/v1/auth/resend-verification",
        json={"email": "resend@auracles.space"},
    )

    sent_emails = auth_test_context["sent_emails"]

    assert response.status_code == 200
    assert response.json() == {"message": "If email is new, verification sent."}
    assert len(sent_emails.calls) == 2
    assert sent_emails.calls[0]["token"] != sent_emails.calls[1]["token"]


async def test_resend_verification_for_unknown_email_does_not_send(
    client: AsyncClient,
    migrated_database: None,
    auth_test_context: dict[str, Any],
) -> None:
    """Unknown email resend still returns the generic no-enumeration response."""
    response = await client.post(
        "/v1/auth/resend-verification",
        json={"email": "unknown@auracles.space"},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "If email is new, verification sent."}
    assert auth_test_context["sent_emails"].calls == []


async def test_resend_verification_rate_limits_per_email(
    client: AsyncClient,
    migrated_database: None,
    auth_test_context: dict[str, Any],
) -> None:
    """Resend verification allows three hourly attempts and rejects the fourth."""
    for _attempt in range(3):
        response = await client.post(
            "/v1/auth/resend-verification",
            json={"email": "limited@auracles.space"},
        )
        assert response.status_code == 200

    response = await client.post(
        "/v1/auth/resend-verification",
        json={"email": "limited@auracles.space"},
    )

    assert response.status_code == 429


async def test_register_rejects_weak_password_and_missing_roles(
    client: AsyncClient,
    migrated_database: None,
    auth_test_context: dict[str, Any],
) -> None:
    """Registration request validation rejects weak passwords and missing roles."""
    weak_password_response = await client.post(
        "/v1/auth/register",
        json={
            "email": "weak@auracles.space",
            "password": "short9",
            "display_name": "Weak User",
            "roles": ["operator"],
        },
    )
    missing_roles_response = await client.post(
        "/v1/auth/register",
        json={
            "email": "noroles@auracles.space",
            "password": "CorrectHorse9",
            "display_name": "No Roles",
            "roles": [],
        },
    )

    assert weak_password_response.status_code == 422
    assert missing_roles_response.status_code == 422
    assert auth_test_context["sent_emails"].calls == []
