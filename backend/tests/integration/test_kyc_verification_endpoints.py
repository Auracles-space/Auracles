"""Integration tests for the Persona identity-verification session endpoint.

Covers `POST /v1/settings/kyc/session`: authed users start an inquiry and get a
hosted link; the inquiry is persisted and the user is marked pending.

Maps to: identity verification design (2026-06-24), build slice 1c.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.integrations.persona import PersonaInquiry
from app.main import app
from app.modules.auth.models import IdentityVerification, User, UserRole
from app.modules.settings import service as settings_service
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async


class FakeRateLimitRedis:
    """In-memory Redis double supporting the rate limiter's commands."""

    def __init__(self) -> None:
        """Create empty counter state."""
        self.counters: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        """Increment and return a counter."""
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        """Record an expiry (no-op for the in-memory double)."""
        return True

    async def ttl(self, key: str) -> int:
        """Return a positive TTL so the limiter never repairs the window."""
        return 3600


async def _fake_create_inquiry(*, reference_id: str, **_: Any) -> PersonaInquiry:
    """Return a deterministic Persona inquiry without any network call."""
    return PersonaInquiry(
        inquiry_id=f"inq_{reference_id[:8]}",
        hosted_url=f"https://withpersona.com/verify?inquiry-id=inq_{reference_id[:8]}",
    )


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


@pytest.fixture
async def verification_context() -> AsyncIterator[None]:
    """Reset identity state and stub Redis + Persona for the session endpoint."""
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()

    app.dependency_overrides[get_redis] = lambda: FakeRateLimitRedis()
    original_create = settings_service.persona.create_inquiry
    settings_service.persona.create_inquiry = _fake_create_inquiry  # type: ignore[assignment]
    try:
        yield
    finally:
        settings_service.persona.create_inquiry = original_create  # type: ignore[assignment]
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def _create_user(email: str, roles: list[str]) -> UUID:
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


def _auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_start_session_creates_inquiry_and_marks_pending(
    client: AsyncClient,
    migrated_database: None,
    verification_context: None,
) -> None:
    """Starting a session returns a hosted URL and records the inquiry."""
    user_id = await _create_user("verify@auracles.space", ["operator"])

    response = await client.post(
        "/v1/settings/kyc/session",
        headers=_auth_headers(user_id, ["operator"]),
    )

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        inquiry = await session.scalar(
            select(IdentityVerification).where(
                IdentityVerification.user_id == user_id
            )
        )
        audit_log = await session.scalar(
            select(AuditLog).where(AuditLog.action == "kyc_status_change")
        )

    assert response.status_code == 200
    assert response.json()["hosted_url"].startswith("https://withpersona.com/verify")
    assert response.json()["inquiry_id"].startswith("inq_")
    assert user is not None and user.kyc_status == "pending"
    assert inquiry is not None and inquiry.status == "created"
    assert audit_log is not None


async def test_start_session_requires_authentication(
    client: AsyncClient,
    migrated_database: None,
    verification_context: None,
) -> None:
    """An unauthenticated session start is rejected with 401."""
    response = await client.post("/v1/settings/kyc/session")

    assert response.status_code == 401


async def test_start_session_conflicts_when_already_verified(
    client: AsyncClient,
    migrated_database: None,
    verification_context: None,
) -> None:
    """A verified user cannot start a new verification session."""
    user_id = await _create_user("done@auracles.space", ["operator"])
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.kyc_status = "verified"
        await session.commit()

    response = await client.post(
        "/v1/settings/kyc/session",
        headers=_auth_headers(user_id, ["operator"]),
    )

    assert response.status_code == 409
