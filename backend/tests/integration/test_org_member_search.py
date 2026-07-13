"""Integration tests for admin-only org invitation member search.

Covers the enumeration guard around invite typeahead suggestions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password, hash_token
from app.main import app
from app.modules.auth.models import User
from app.modules.notifications.models import Notification
from app.modules.organizations.models import OrgInvitation
from tests.integration.test_auth_sessions import FakeRedis
from tests.integration.test_organizations_endpoints import (
    add_member,
    auth,
    create_org,
    create_user,
)
from tests.support.db_cleanup import clear_identity_state_async


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure application tables exist for member-search endpoint tests."""
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
async def member_search_test_context() -> AsyncIterator[FakeRedis]:
    """Reset invitation-related state and install fake Redis for rate limits."""
    fake_redis = FakeRedis()
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(Notification))
        await session.execute(delete(OrgInvitation))
        await clear_identity_state_async(session)
        await session.commit()

    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        async with async_session_factory() as session:
            await session.execute(delete(Notification))
            await session.execute(delete(OrgInvitation))
            await clear_identity_state_async(session)
            await session.commit()
        await engine.dispose()


async def _create_user_with_profile(
    *,
    email: str,
    display_name: str,
    avatar_url: str | None = None,
) -> UUID:
    """Create a verified user with the exact profile values needed by a test."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=display_name,
                avatar_url=avatar_url,
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            return user.id


async def _create_pending_invitation(
    *,
    org_id: str,
    invited_by: UUID,
    email: str,
) -> None:
    """Insert one pending invitation directly for exclusion-path tests."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgInvitation(
                    org_id=UUID(org_id),
                    email=email,
                    role="member",
                    invited_by=invited_by,
                    status="pending",
                    token_hash=hash_token("fixed-token"),
                    expires_at=datetime.now(UTC) + timedelta(days=7),
                )
            )


async def test_search_returns_masked_matches_for_admin(
    client: AsyncClient,
    migrated_database: None,
    member_search_test_context: FakeRedis,
) -> None:
    """Admin search returns masked suggestions without exposing full emails."""
    del migrated_database, member_search_test_context
    owner_id = await create_user("member-search-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "member-search")
    await _create_user_with_profile(
        email="joanna@example.com",
        display_name="Joanna Reed",
        avatar_url="https://cdn.example.com/joanna.png",
    )

    response = await client.get(
        f"/v1/orgs/{org['id']}/member-search",
        params={"q": "joa"},
        headers=auth(owner_token),
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0] == {
        "user_id": str(results[0]["user_id"]),
        "display_name": "Joanna Reed",
        "avatar_url": "https://cdn.example.com/joanna.png",
        "masked_email": "j•••@example.com",
    }
    assert "email" not in results[0]


async def test_search_under_three_chars_is_empty(
    client: AsyncClient,
    migrated_database: None,
    member_search_test_context: FakeRedis,
) -> None:
    """Queries shorter than 3 chars return 200 with an empty result set."""
    del migrated_database, member_search_test_context
    owner_id = await create_user("member-search-short")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "member-search-short")

    response = await client.get(
        f"/v1/orgs/{org['id']}/member-search",
        params={"q": "jo"},
        headers=auth(owner_token),
    )

    assert response.status_code == 200
    assert response.json() == {"results": []}


async def test_search_requires_admin(
    client: AsyncClient,
    migrated_database: None,
    member_search_test_context: FakeRedis,
) -> None:
    """Plain org members cannot use the invite member-search endpoint."""
    del migrated_database, member_search_test_context
    owner_id = await create_user("member-search-rbac-owner")
    member_id = await create_user("member-search-rbac-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "member-search-rbac")
    await add_member(str(org["id"]), member_id, "member")

    response = await client.get(
        f"/v1/orgs/{org['id']}/member-search",
        params={"q": "joa"},
        headers=auth(create_access_token(member_id, [])),
    )

    assert response.status_code == 403


async def test_search_excludes_members_and_invited_users(
    client: AsyncClient,
    migrated_database: None,
    member_search_test_context: FakeRedis,
) -> None:
    """Matching users already in the org or already invited are filtered out."""
    del migrated_database, member_search_test_context
    owner_id = await create_user("member-search-exclude-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "member-search-exclude")
    member_user_id = await _create_user_with_profile(
        email="excmember@member.com",
        display_name="Exclude Member",
    )
    await add_member(str(org["id"]), member_user_id, "member")
    await _create_user_with_profile(
        email="excinvited@invited.com",
        display_name="Exclude Invited",
    )
    await _create_pending_invitation(
        org_id=str(org["id"]),
        invited_by=owner_id,
        email="excinvited@invited.com",
    )
    await _create_user_with_profile(
        email="excvisible@match.com",
        display_name="Exclude Visible",
    )

    response = await client.get(
        f"/v1/orgs/{org['id']}/member-search",
        params={"q": "exc"},
        headers=auth(owner_token),
    )

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "user_id": str(response.json()["results"][0]["user_id"]),
                "display_name": "Exclude Visible",
                "avatar_url": None,
                "masked_email": "e•••@match.com",
            }
        ]
    }


async def test_search_rate_limit_returns_429(
    client: AsyncClient,
    migrated_database: None,
    member_search_test_context: FakeRedis,
) -> None:
    """The per-caller member-search limiter returns 429 after the budget is spent."""
    del migrated_database
    owner_id = await create_user("member-search-limit-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "member-search-limit")
    member_search_test_context.counters[f"rate_limit:org_member_search:{owner_id}"] = 30

    response = await client.get(
        f"/v1/orgs/{org['id']}/member-search",
        params={"q": "joa"},
        headers=auth(owner_token),
    )

    assert response.status_code == 429
