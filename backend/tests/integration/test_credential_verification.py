"""Integration tests for manual Credential verification (Admin-driven)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient  # noqa: F401
from sqlalchemy import create_engine, delete, inspect, select  # noqa: F401

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.attestation.models import AttestationUploadSession, Credential
from app.modules.auth.models import User, UserRole
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for routes that do not use Redis directly."""


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure credential tables exist for endpoint tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url, pool_pre_ping=True
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


async def reset_credential_state() -> None:
    """Remove credential test rows in dependency order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(Credential))
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
async def credential_context() -> AsyncIterator[FakeRedis]:
    """Reset credential/auth state and install a Redis test double."""
    fake_redis = FakeRedis()
    await engine.dispose()
    await reset_credential_state()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await reset_credential_state()
        await engine.dispose()


async def create_user(email: str, roles: list[str]) -> UUID:
    """Create a verified user with approved role rows."""
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
                    UserRole(user_id=user.id, role=role, approved_at=datetime.now(UTC))
                )
        return user.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


def test_credentials_table_has_verification_columns(migrated_database: None) -> None:
    """Migration adds verification + metadata columns to credentials."""
    del migrated_database
    sync_engine = create_engine(app.state.settings.sync_database_url)
    try:
        columns = {
            col["name"] for col in inspect(sync_engine).get_columns("credentials")
        }
    finally:
        sync_engine.dispose()
    assert {
        "verification_status",
        "credential_type",
        "verification_url",
        "reference_number",
        "issuer_type",
        "submitted_at",
        "verified_at",
        "reviewed_by",
        "rejection_reason",
    } <= columns
