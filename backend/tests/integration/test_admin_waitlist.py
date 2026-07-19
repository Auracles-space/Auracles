"""Integration tests for the admin waitlist oversight endpoint.

Read-only surface: admins list and search pre-launch waitlist signups. Only
admins may call it.
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
from app.modules.waitlist.models import WaitlistEntry
from tests.support.db_cleanup import clear_identity_state_async


async def reset_admin_waitlist_state() -> None:
    """Remove waitlist and identity test data."""
    async with async_session_factory() as session:
        await session.execute(delete(WaitlistEntry))
        await clear_identity_state_async(session)
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure waitlist tables exist for admin oversight tests."""
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
async def admin_waitlist_context() -> AsyncIterator[None]:
    """Reset auth/waitlist state around each test."""
    await engine.dispose()
    await reset_admin_waitlist_state()
    try:
        yield
    finally:
        await reset_admin_waitlist_state()
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


async def _create_entry(*, email: str, source: str | None) -> None:
    """Create one waitlist entry."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(WaitlistEntry(email=email, source=source))


def _auth_headers(user_id: UUID, *, roles: list[str]) -> dict[str, str]:
    """Build bearer auth headers for a user with the given roles."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_admin_lists_waitlist_entries(
    client: AsyncClient,
    migrated_database: None,
    admin_waitlist_context: None,
) -> None:
    """Admin sees waitlist signups with email and source."""
    del migrated_database, admin_waitlist_context
    admin_id = await _create_user(role="admin")
    await _create_entry(email="early@founder.com", source="hero")

    response = await client.get(
        "/v1/admin/waitlist",
        headers=_auth_headers(admin_id, roles=["admin"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["email"] == "early@founder.com"
    assert item["source"] == "hero"


async def test_admin_searches_waitlist_by_email(
    client: AsyncClient,
    migrated_database: None,
    admin_waitlist_context: None,
) -> None:
    """The email query narrows the waitlist to matching signups."""
    del migrated_database, admin_waitlist_context
    admin_id = await _create_user(role="admin")
    await _create_entry(email="alice@acme.com", source="hero")
    await _create_entry(email="bob@other.com", source="footer")

    response = await client.get(
        "/v1/admin/waitlist",
        headers=_auth_headers(admin_id, roles=["admin"]),
        params={"query": "acme"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["email"] == "alice@acme.com"


async def test_non_admin_cannot_list_waitlist(
    client: AsyncClient,
    migrated_database: None,
    admin_waitlist_context: None,
) -> None:
    """A contributor token is rejected from the waitlist directory."""
    del migrated_database, admin_waitlist_context
    contributor_id = await _create_user(role="contributor")

    response = await client.get(
        "/v1/admin/waitlist",
        headers=_auth_headers(contributor_id, roles=["contributor"]),
    )

    assert response.status_code == 403
