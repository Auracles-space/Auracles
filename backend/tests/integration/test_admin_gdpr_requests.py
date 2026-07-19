"""Integration tests for the admin GDPR request oversight endpoints.

Read-only queues: admins list account-deletion and data-export requests to
monitor compliance. The internal export bundle key must never appear, and only
admins may call these endpoints.
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
from app.modules.gdpr.models import AccountDeletionRequest, DataExportRequest
from tests.support.db_cleanup import clear_identity_state_async


async def reset_admin_gdpr_state() -> None:
    """Remove GDPR request test data in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(AccountDeletionRequest))
        await session.execute(delete(DataExportRequest))
        await clear_identity_state_async(session)
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure GDPR tables exist for admin oversight tests."""
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
async def admin_gdpr_context() -> AsyncIterator[None]:
    """Reset auth/GDPR state around each test."""
    await engine.dispose()
    await reset_admin_gdpr_state()
    try:
        yield
    finally:
        await reset_admin_gdpr_state()
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


def _auth_headers(user_id: UUID, *, roles: list[str]) -> dict[str, str]:
    """Build bearer auth headers for a user with the given roles."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_admin_lists_blocked_deletion_requests(
    client: AsyncClient,
    migrated_database: None,
    admin_gdpr_context: None,
) -> None:
    """Admin sees a blocked deletion request with its blocked reasons."""
    del migrated_database, admin_gdpr_context
    admin_id = await _create_user(role="admin")
    subject_id = await _create_user(role="contributor")
    async with async_session_factory() as session:
        async with session.begin():
            request = AccountDeletionRequest(
                user_id=subject_id,
                status="blocked",
                blocked_reasons=[{"code": "held_escrow", "count": 2}],
            )
            session.add(request)
            await session.flush()
            request_id = request.id

    response = await client.get(
        "/v1/admin/gdpr/deletion-requests",
        headers=_auth_headers(admin_id, roles=["admin"]),
        params={"status": "blocked"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["request_id"] == str(request_id)
    assert item["user_id"] == str(subject_id)
    assert item["status"] == "blocked"
    assert item["blocked_reasons"] == [{"code": "held_escrow", "count": 2}]


async def test_admin_export_queue_hides_bundle_key(
    client: AsyncClient,
    migrated_database: None,
    admin_gdpr_context: None,
) -> None:
    """The export queue never leaks the internal bundle storage key."""
    del migrated_database, admin_gdpr_context
    admin_id = await _create_user(role="admin")
    subject_id = await _create_user(role="operator")
    async with async_session_factory() as session:
        async with session.begin():
            export = DataExportRequest(
                user_id=subject_id,
                status="ready",
                bundle_key="private/exports/secret-bundle.zip",
            )
            session.add(export)
            await session.flush()

    response = await client.get(
        "/v1/admin/gdpr/export-requests",
        headers=_auth_headers(admin_id, roles=["admin"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "ready"
    assert "secret-bundle.zip" not in response.text
    assert "bundle_key" not in body["items"][0]


async def test_non_admin_cannot_list_gdpr_requests(
    client: AsyncClient,
    migrated_database: None,
    admin_gdpr_context: None,
) -> None:
    """A contributor token is rejected from the GDPR oversight queues."""
    del migrated_database, admin_gdpr_context
    contributor_id = await _create_user(role="contributor")

    response = await client.get(
        "/v1/admin/gdpr/deletion-requests",
        headers=_auth_headers(contributor_id, roles=["contributor"]),
    )

    assert response.status_code == 403
