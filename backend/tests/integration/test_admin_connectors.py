"""Integration tests for the admin connector oversight endpoint.

Read-only surface: admins audit user OAuth connections to external file
providers. Encrypted access/refresh tokens must never appear, and only admins
may call it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.integrations.models import OAuthConnection
from tests.support.db_cleanup import clear_identity_state_async


async def reset_admin_connector_state() -> None:
    """Remove connector test data in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(OAuthConnection))
        await clear_identity_state_async(session)
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure integration tables exist for admin connector tests."""
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
async def admin_connector_context() -> AsyncIterator[None]:
    """Reset auth/connector state around each test."""
    await engine.dispose()
    await reset_admin_connector_state()
    try:
        yield
    finally:
        await reset_admin_connector_state()
        await engine.dispose()


async def _create_user(*, role: str) -> UUID:
    """Create a verified user holding one role."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{role}-{uuid4()}@auracles.space",
                password_hash="not-used",
                display_name=role.title(),
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(user_id=user.id, role=role, approved_at=datetime.now(UTC))
            )
        return user.id


async def _create_connection(*, user_id: UUID, status: str) -> UUID:
    """Create one OAuth connection with encrypted tokens set."""
    async with async_session_factory() as session:
        async with session.begin():
            connection = OAuthConnection(
                user_id=user_id,
                provider="google_drive",
                provider_account_email="connected@example.com",
                access_token_encrypted="gAAAA-secret-access-token",
                refresh_token_encrypted="gAAAA-secret-refresh-token",
                scopes="https://www.googleapis.com/auth/drive.readonly",
                status=status,
            )
            session.add(connection)
            await session.flush()
            return connection.id


def _auth_headers(user_id: UUID, *, roles: list[str]) -> dict[str, str]:
    """Build bearer auth headers for a user with the given roles."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_admin_lists_connectors_without_tokens(
    client: AsyncClient,
    migrated_database: None,
    admin_connector_context: None,
) -> None:
    """Admin sees connection metadata but never the encrypted tokens."""
    del migrated_database, admin_connector_context
    admin_id = await _create_user(role="admin")
    owner_id = await _create_user(role="contributor")
    connection_id = await _create_connection(user_id=owner_id, status="active")

    response = await client.get(
        "/v1/admin/connectors",
        headers=_auth_headers(admin_id, roles=["admin"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["connection_id"] == str(connection_id)
    assert item["user_id"] == str(owner_id)
    assert item["provider"] == "google_drive"
    assert item["provider_account_email"] == "connected@example.com"
    assert item["status"] == "active"
    # Token guard: encrypted tokens must never leak.
    assert "gAAAA-secret" not in response.text
    assert "access_token_encrypted" not in item
    assert "refresh_token_encrypted" not in item


async def test_admin_filters_connectors_by_status(
    client: AsyncClient,
    migrated_database: None,
    admin_connector_context: None,
) -> None:
    """The status filter narrows to reauth_required connections only."""
    del migrated_database, admin_connector_context
    admin_id = await _create_user(role="admin")
    owner_id = await _create_user(role="contributor")
    await _create_connection(user_id=owner_id, status="active")
    second_owner = await _create_user(role="contributor")
    await _create_connection(user_id=second_owner, status="reauth_required")

    response = await client.get(
        "/v1/admin/connectors",
        headers=_auth_headers(admin_id, roles=["admin"]),
        params={"status": "reauth_required"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "reauth_required"


async def test_non_admin_cannot_list_connectors(
    client: AsyncClient,
    migrated_database: None,
    admin_connector_context: None,
) -> None:
    """A contributor token is rejected from the connector directory."""
    del migrated_database, admin_connector_context
    contributor_id = await _create_user(role="contributor")

    response = await client.get(
        "/v1/admin/connectors",
        headers=_auth_headers(contributor_id, roles=["contributor"]),
    )

    assert response.status_code == 403
