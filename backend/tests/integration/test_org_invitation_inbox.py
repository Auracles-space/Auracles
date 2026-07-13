"""Integration tests for the invitee invitation inbox.

Covers token-free listing of invitations addressed to the authenticated user.
Maps to the org-invitation-inbox design.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token
from app.main import app
from app.modules.auth.models import User
from app.modules.notifications.models import Notification
from app.modules.organizations.models import OrgInvitation, Organization
from tests.integration.test_auth_sessions import FakeRedis
from tests.integration.test_org_invitations_endpoints import _mute_email
from tests.integration.test_organizations_endpoints import auth, create_org, create_user
from tests.support.db_cleanup import clear_identity_state_async


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure application tables exist for invitation inbox tests."""
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
async def invitation_test_context() -> AsyncIterator[FakeRedis]:
    """Reset invitation state and install fake Redis for invitation tests."""
    fake_redis = FakeRedis()
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(Notification))
        await session.execute(delete(OrgInvitation))
        await session.execute(delete(Organization))
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
            await session.execute(delete(Organization))
            await clear_identity_state_async(session)
            await session.commit()
        await engine.dispose()


@pytest.fixture
async def authed_client(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
) -> tuple[AsyncClient, User, str]:
    """Return an authenticated client plus the corresponding user row."""
    del migrated_database, invitation_test_context
    user_id = await create_user("invitee")
    token = create_access_token(user_id, [])
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        return client, user, token


@pytest.fixture
async def other_user_org_with_invite(
    client: AsyncClient,
    authed_client: tuple[AsyncClient, User, str],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, str]:
    """Seed one matching pending invite plus rows that should be filtered out."""
    _mute_email(monkeypatch)
    _, me, _ = authed_client
    owner_id = await create_user("org-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "Meridian")

    matching = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": me.email, "role": "member"},
        headers=auth(owner_token),
    )
    assert matching.status_code == 201

    other_email = f"other-{uuid4().hex[:8]}@auracles.space"
    not_me = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": other_email, "role": "member"},
        headers=auth(owner_token),
    )
    assert not_me.status_code == 201

    accepted = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": f'accepted-{uuid4().hex[:8]}@auracles.space', "role": "admin"},
        headers=auth(owner_token),
    )
    assert accepted.status_code == 201

    accepted_id = UUID(accepted.json()["id"])
    async with async_session_factory() as session:
        async with session.begin():
            invitation = await session.get(OrgInvitation, accepted_id)
            assert invitation is not None
            invitation.status = "accepted"
            invitation.responded_at = datetime.now(UTC)

    return {"invitation_id": matching.json()["id"]}


@pytest.mark.asyncio
async def test_received_lists_only_my_pending_invitations(
    authed_client: tuple[AsyncClient, User, str],
    other_user_org_with_invite: dict[str, str],
) -> None:
    """GET /org-invitations/received returns pending invites for my email only."""
    del other_user_org_with_invite
    client, _, token = authed_client

    resp = await client.get("/v1/org-invitations/received", headers=auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["invitations"]) == 1
    inv = body["invitations"][0]
    assert inv["role"] == "member"
    assert inv["org"]["name"] == "Meridian"
    assert "token" not in inv
    assert "token_hash" not in inv
    assert set(inv.keys()) == {"id", "org", "role", "invited_by_name", "created_at"}


@pytest.mark.asyncio
async def test_received_requires_auth(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
) -> None:
    """Unauthenticated caller gets 401."""
    del migrated_database, invitation_test_context

    resp = await client.get("/v1/org-invitations/received")

    assert resp.status_code == 401
