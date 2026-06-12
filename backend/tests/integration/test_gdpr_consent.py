"""Integration tests for Phase 5c Slice 2 GDPR consent flows."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth import service as auth_service
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import PlatformConfig
from app.modules.gdpr.models import ConsentLog
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for registration verification-token writes."""

    def __init__(self) -> None:
        """Create empty string storage."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a string value with a TTL."""
        self.values[key] = value
        self.ttls[key] = seconds


class SentEmails:
    """Capture auth email task dispatches."""

    def __init__(self) -> None:
        """Create empty dispatch records."""
        self.verification_calls: list[dict[str, str]] = []

    def verification_delay(self, email: str, token: str) -> None:
        """Record a verification-email task dispatch."""
        self.verification_calls.append({"email": email, "token": token})


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Phase 5c GDPR tables and config rows exist."""
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
async def consent_test_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset auth/consent state and install Redis/email test doubles."""
    fake_redis = FakeRedis()
    sent_emails = SentEmails()
    await engine.dispose()
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(ConsentLog))
            await session.execute(delete(AuditLog))
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

    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr(
        auth_service.send_verification_email,
        "delay",
        sent_emails.verification_delay,
    )
    try:
        yield {"redis": fake_redis, "sent_emails": sent_emails}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await engine.dispose()


async def create_verified_user(email: str) -> UUID:
    """Create a verified Operator without consent history."""
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
            session.add(
                UserRole(
                    user_id=user.id,
                    role="operator",
                    approved_at=datetime.now(UTC),
                )
            )
        return user.id


def auth_headers(user_id: UUID, roles: list[str] | None = None) -> dict[str, str]:
    """Create bearer auth headers for a GDPR consent test user."""
    token = create_access_token(user_id=user_id, roles=roles or ["operator"])
    return {"Authorization": f"Bearer {token}"}


async def test_registration_records_current_consent_versions(
    client: AsyncClient,
    migrated_database: None,
    consent_test_context: dict[str, Any],
) -> None:
    """Registration captures TOS and Privacy Policy consent with request context."""
    del migrated_database

    response = await client.post(
        "/v1/auth/register",
        json={
            "email": "consent-register@auracles.space",
            "password": "CorrectHorse9",
            "display_name": "Consent Register",
            "roles": ["operator"],
        },
        headers={"User-Agent": "Consent Browser"},
    )

    async with async_session_factory() as session:
        user = await session.scalar(
            select(User).where(User.email == "consent-register@auracles.space")
        )
        assert user is not None
        logs = (
            await session.execute(
                select(ConsentLog).where(ConsentLog.user_id == user.id)
            )
        ).scalars().all()
        audits = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "consent_recorded",
                    AuditLog.actor_id == user.id,
                )
            )
        ).scalars().all()

    assert response.status_code == 200
    assert {log.document_type for log in logs} == {
        "terms_of_service",
        "privacy_policy",
    }
    assert {log.version for log in logs} == {"1.0"}
    assert {log.user_agent for log in logs} == {"Consent Browser"}
    assert len(audits) == 2
    assert len(consent_test_context["sent_emails"].verification_calls) == 1


async def test_user_can_accept_current_consent_and_view_history(
    client: AsyncClient,
    migrated_database: None,
    consent_test_context: dict[str, Any],
) -> None:
    """Authenticated users can record current legal consent and list history."""
    del migrated_database, consent_test_context
    user_id = await create_verified_user("consent-history@auracles.space")

    accept = await client.post(
        "/v1/gdpr/consent",
        json={"accept_terms": True, "accept_privacy_policy": True},
        headers={**auth_headers(user_id), "User-Agent": "History Browser"},
    )
    history = await client.get(
        "/v1/gdpr/consent",
        headers=auth_headers(user_id),
    )

    assert accept.status_code == 200
    assert history.status_code == 200
    assert accept.json()["missing_documents"] == []
    assert history.json()["current_versions"] == {
        "terms_of_service": "1.0",
        "privacy_policy": "1.0",
    }
    assert history.json()["missing_documents"] == []
    assert {
        item["document_type"] for item in history.json()["items"]
    } == {"terms_of_service", "privacy_policy"}


async def test_consent_history_reports_missing_documents_after_version_bump(
    client: AsyncClient,
    migrated_database: None,
    consent_test_context: dict[str, Any],
) -> None:
    """Consent status reports missing current versions after legal version bumps."""
    del migrated_database, consent_test_context
    user_id = await create_verified_user("consent-bump@auracles.space")
    await client.post(
        "/v1/gdpr/consent",
        json={"accept_terms": True, "accept_privacy_policy": True},
        headers=auth_headers(user_id),
    )
    async with async_session_factory() as session:
        tos = await session.get(PlatformConfig, "consent_version_terms_of_service")
        assert tos is not None
        tos.value = "2.0"
        await session.commit()

    history = await client.get(
        "/v1/gdpr/consent",
        headers=auth_headers(user_id),
    )

    assert history.status_code == 200
    assert history.json()["current_versions"]["terms_of_service"] == "2.0"
    assert history.json()["missing_documents"] == ["terms_of_service"]
