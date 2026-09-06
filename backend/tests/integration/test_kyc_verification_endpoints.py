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

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.integrations.persona import PersonaInquiryStatus
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


def _fake_hosted_url(*, reference_id: str, **_: Any) -> str:
    """Return a deterministic hosted-flow link without reading settings.

    Hosted flow needs no network call at all — the URL is built locally — so
    this stands in only to keep the test independent of whether
    PERSONA_ENVIRONMENT_ID happens to be set in the runner's environment.
    """
    return (
        "https://inquiry.withpersona.com/verify"
        f"?inquiry-template-id=itmpl_test&environment-id=env_test"
        f"&reference-id={reference_id}"
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
async def verification_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[None]:
    """Reset identity state and stub Redis + Persona for the session endpoint.

    The platform defaults to ``KYC_PROVIDER=manual``, under which these routes
    are deliberately unreachable, so the provider flow is switched on explicitly
    here — that is the configuration these tests are about.
    """
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()

    monkeypatch.setattr(get_settings(), "kyc_provider", "persona")
    app.dependency_overrides[get_redis] = lambda: FakeRateLimitRedis()
    original_create = settings_service.persona.build_hosted_inquiry_url
    settings_service.persona.build_hosted_inquiry_url = _fake_hosted_url  # type: ignore[assignment]
    try:
        yield
    finally:
        settings_service.persona.build_hosted_inquiry_url = original_create  # type: ignore[assignment]
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
    """Starting a session returns a hosted URL and records a pending row.

    Under hosted flow the inquiry does not exist yet — Persona mints it when
    the user opens the link — so the row is written with a null ``inquiry_id``
    and the response carries none. The id arrives later, on the return sync or
    the webhook.
    """
    user_id = await _create_user("verify@auracles.space", ["operator"])

    response = await client.post(
        "/v1/settings/kyc/session",
        headers=_auth_headers(user_id, ["operator"]),
    )

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        inquiry = await session.scalar(
            select(IdentityVerification).where(IdentityVerification.user_id == user_id)
        )
        audit_log = await session.scalar(
            select(AuditLog).where(AuditLog.action == "kyc_status_change")
        )

    assert response.status_code == 200
    assert response.json()["hosted_url"].startswith(
        "https://inquiry.withpersona.com/verify"
    )
    assert response.json()["inquiry_id"] is None
    assert user is not None and user.kyc_status == "pending"
    assert inquiry is not None and inquiry.status == "created"
    assert inquiry.inquiry_id is None
    assert audit_log is not None


async def test_start_session_requires_authentication(
    client: AsyncClient,
    migrated_database: None,
    verification_context: None,
) -> None:
    """An unauthenticated session start is rejected with 401."""
    response = await client.post("/v1/settings/kyc/session")

    assert response.status_code == 401


async def _seed_inquiry(user_id: UUID, inquiry_id: str | None) -> None:
    """Seed a pending identity-verification row as `session` start would."""
    async with async_session_factory() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            assert user is not None
            user.kyc_status = "pending"
            session.add(
                IdentityVerification(
                    user_id=user_id,
                    provider="persona",
                    inquiry_id=inquiry_id,
                    status="created",
                )
            )


async def test_sync_applies_approved_inquiry_and_verifies_user(
    client: AsyncClient,
    migrated_database: None,
    verification_context: None,
) -> None:
    """Syncing an approved inquiry flips the owner to verified.

    Backs the on-return path: the app reads the verdict directly from Persona
    so a completed check resolves without waiting for the inbound webhook.
    """
    user_id = await _create_user("sync@auracles.space", ["operator"])
    await _seed_inquiry(user_id, "inq_sync1")

    async def fake_fetch(*, inquiry_id: str, **_: Any) -> PersonaInquiryStatus:
        return PersonaInquiryStatus(
            inquiry_id=inquiry_id,
            status="approved",
            reference_id=str(user_id),
        )

    original = settings_service.persona.fetch_inquiry
    settings_service.persona.fetch_inquiry = fake_fetch  # type: ignore[assignment]
    try:
        response = await client.post(
            "/v1/settings/kyc/sync",
            headers=_auth_headers(user_id, ["operator"]),
            json={"inquiry_id": "inq_sync1"},
        )
    finally:
        settings_service.persona.fetch_inquiry = original  # type: ignore[assignment]

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        inquiry = await session.scalar(
            select(IdentityVerification).where(
                IdentityVerification.inquiry_id == "inq_sync1"
            )
        )

    assert response.status_code == 200
    assert response.json()["kyc_status"] == "verified"
    assert user is not None and user.kyc_status == "verified"
    assert inquiry is not None and inquiry.status == "approved"


async def test_sync_keeps_pending_when_inquiry_not_terminal(
    client: AsyncClient,
    migrated_database: None,
    verification_context: None,
) -> None:
    """A still-pending inquiry leaves the user pending, no false verdict."""
    user_id = await _create_user("waiting@auracles.space", ["operator"])
    await _seed_inquiry(user_id, "inq_wait1")

    async def fake_fetch(*, inquiry_id: str, **_: Any) -> PersonaInquiryStatus:
        return PersonaInquiryStatus(
            inquiry_id=inquiry_id, status="pending", reference_id=str(user_id)
        )

    original = settings_service.persona.fetch_inquiry
    settings_service.persona.fetch_inquiry = fake_fetch  # type: ignore[assignment]
    try:
        response = await client.post(
            "/v1/settings/kyc/sync",
            headers=_auth_headers(user_id, ["operator"]),
            json={"inquiry_id": "inq_wait1"},
        )
    finally:
        settings_service.persona.fetch_inquiry = original  # type: ignore[assignment]

    assert response.status_code == 200
    assert response.json()["kyc_status"] == "pending"


async def test_sync_rejects_inquiry_owned_by_another_user(
    client: AsyncClient,
    migrated_database: None,
    verification_context: None,
) -> None:
    """Syncing another user's inquiry is a 404 — no cross-account writes."""
    owner_id = await _create_user("owner@auracles.space", ["operator"])
    attacker_id = await _create_user("attacker@auracles.space", ["operator"])
    await _seed_inquiry(owner_id, "inq_owned")

    async def fake_fetch(*, inquiry_id: str, **_: Any) -> PersonaInquiryStatus:
        return PersonaInquiryStatus(
            inquiry_id=inquiry_id, status="approved", reference_id=str(owner_id)
        )

    original = settings_service.persona.fetch_inquiry
    settings_service.persona.fetch_inquiry = fake_fetch  # type: ignore[assignment]
    try:
        response = await client.post(
            "/v1/settings/kyc/sync",
            headers=_auth_headers(attacker_id, ["operator"]),
            json={"inquiry_id": "inq_owned"},
        )
    finally:
        settings_service.persona.fetch_inquiry = original  # type: ignore[assignment]

    async with async_session_factory() as session:
        owner = await session.get(User, owner_id)

    assert response.status_code == 404
    # The owner's status is untouched by the attacker's sync attempt.
    assert owner is not None and owner.kyc_status == "pending"


async def test_sync_requires_authentication(
    client: AsyncClient,
    migrated_database: None,
    verification_context: None,
) -> None:
    """An unauthenticated sync is rejected with 401."""
    response = await client.post(
        "/v1/settings/kyc/sync", json={"inquiry_id": "inq_x"}
    )

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


async def test_sync_rejects_inquiry_belonging_to_another_user(
    client: AsyncClient,
    migrated_database: None,
    verification_context: None,
) -> None:
    """An inquiry Persona says belongs to somebody else is refused.

    The inquiry id is supplied by the caller (Persona appends it to the return
    URL), and under hosted flow a row awaiting its id would otherwise adopt
    whatever id was named — letting a caller claim a stranger's approved
    inquiry and verify themselves with it. Persona's reference-id is the
    authority, and a mismatch must 404 without touching KYC state.
    """
    attacker_id = await _create_user("attacker@auracles.space", ["operator"])
    victim_id = await _create_user("victim@auracles.space", ["operator"])
    # The attacker has a pending hosted-flow row with no inquiry id yet.
    await _seed_inquiry(attacker_id, None)

    async def fake_fetch(*, inquiry_id: str, **_: Any) -> PersonaInquiryStatus:
        # Persona reports the inquiry as the victim's, not the caller's.
        return PersonaInquiryStatus(
            inquiry_id=inquiry_id,
            status="approved",
            reference_id=str(victim_id),
        )

    original = settings_service.persona.fetch_inquiry
    settings_service.persona.fetch_inquiry = fake_fetch  # type: ignore[assignment]
    try:
        response = await client.post(
            "/v1/settings/kyc/sync",
            headers=_auth_headers(attacker_id, ["operator"]),
            json={"inquiry_id": "inq_victim"},
        )
    finally:
        settings_service.persona.fetch_inquiry = original  # type: ignore[assignment]

    async with async_session_factory() as session:
        attacker = await session.get(User, attacker_id)
        record = await session.scalar(
            select(IdentityVerification).where(
                IdentityVerification.user_id == attacker_id
            )
        )

    assert response.status_code == 404
    assert attacker is not None and attacker.kyc_status == "pending"
    # The row must not have adopted the stranger's inquiry id either.
    assert record is not None and record.inquiry_id is None
