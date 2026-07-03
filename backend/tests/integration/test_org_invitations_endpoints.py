"""Integration tests for organization invitation endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

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
    """Ensure application tables exist for invitation endpoint tests."""
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
    """Reset invitation state and install fake Redis for rate limits."""
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


async def test_invite_creates_pending_and_dispatches_email(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST invitations stores a pending invite and dispatches the email task."""
    del migrated_database, invitation_test_context
    sent: list[tuple[str, str]] = []

    def fake_delay(email: str, org_name: str, role: str, token: str) -> None:
        """Capture the dispatched email payload for assertions."""
        del org_name, role
        sent.append((email, token))

    from app.workers.tasks import org_notifications

    monkeypatch.setattr(org_notifications.send_org_invitation, "delay", fake_delay)
    owner_id = await create_user("inv-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "inv")

    response = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": "Invitee@Auracles.SPACE", "role": "member"},
        headers=auth(owner_token),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "invitee@auracles.space"
    assert body["status"] == "pending"
    assert len(sent) == 1
    async with async_session_factory() as session:
        invite = await session.scalar(select(OrgInvitation))

    assert invite is not None
    assert invite.token_hash == hash_token(sent[0][1])
    assert invite.token_hash != sent[0][1]


def _mute_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the invitation email task for tests that do not inspect it."""
    from app.workers.tasks import org_notifications

    monkeypatch.setattr(
        org_notifications.send_org_invitation,
        "delay",
        lambda *args: None,
    )


async def test_duplicate_pending_invite_conflicts(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second pending invite for the same org/email returns 409."""
    del migrated_database, invitation_test_context
    _mute_email(monkeypatch)
    owner_id = await create_user("inv-dup")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "invdup")

    first = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": "dup@auracles.space", "role": "member"},
        headers=auth(owner_token),
    )
    second = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": "dup@auracles.space", "role": "member"},
        headers=auth(owner_token),
    )

    assert first.status_code == 201
    assert second.status_code == 409


async def test_invitation_list_returns_pending_only(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Listing invitations returns the organization's pending invites."""
    del migrated_database, invitation_test_context
    _mute_email(monkeypatch)
    owner_id = await create_user("inv-list")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "invlist")
    created = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": "list@auracles.space", "role": "admin"},
        headers=auth(owner_token),
    )

    response = await client.get(
        f"/v1/orgs/{org['id']}/invitations",
        headers=auth(owner_token),
    )

    assert created.status_code == 201
    assert response.status_code == 200
    invitations = response.json()["invitations"]
    assert len(invitations) == 1
    assert invitations[0]["email"] == "list@auracles.space"
    assert invitations[0]["status"] == "pending"


async def test_invite_admin_plus_only(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
) -> None:
    """Plain members cannot create invitations."""
    del migrated_database, invitation_test_context
    owner_id = await create_user("inv-rbac-owner")
    member_id = await create_user("inv-rbac-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "invrbac")
    await add_member(str(org["id"]), member_id, "member")

    response = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": "x@auracles.space", "role": "member"},
        headers=auth(create_access_token(member_id, [])),
    )

    assert response.status_code == 403


async def test_revoke_pending_invite(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revoking a pending invitation works once and then conflicts."""
    del migrated_database, invitation_test_context
    _mute_email(monkeypatch)
    owner_id = await create_user("inv-rev")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "invrev")
    created = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": "rev@auracles.space", "role": "member"},
        headers=auth(owner_token),
    )
    invitation_id = created.json()["id"]

    first = await client.delete(
        f"/v1/orgs/{org['id']}/invitations/{invitation_id}",
        headers=auth(owner_token),
    )
    second = await client.delete(
        f"/v1/orgs/{org['id']}/invitations/{invitation_id}",
        headers=auth(owner_token),
    )

    assert first.status_code == 204
    assert second.status_code == 409


async def test_invitation_rate_limit_returns_429(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-org invitation limit returns 429 after 20 requests in an hour."""
    del migrated_database
    _mute_email(monkeypatch)
    owner_id = await create_user("inv-limit")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "invlimit")
    invitation_test_context.counters[f"rate_limit:org_invite:{org['id']}"] = 20

    response = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": "limit@auracles.space", "role": "member"},
        headers=auth(owner_token),
    )

    assert response.status_code == 429


# -- Task 7: Invitation preview, accept, decline --


async def _invite(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    org: dict[str, object],
    owner_token: str,
    email: str,
    role: str = "member",
) -> str:
    """Create an invitation via the API and capture the raw emailed token."""
    captured: list[str] = []

    from app.workers.tasks import org_notifications

    monkeypatch.setattr(
        org_notifications.send_org_invitation,
        "delay",
        lambda _e, _o, _r, t: captured.append(t),
    )
    response = await client.post(
        f"/v1/orgs/{org['id']}/invitations",
        json={"email": email, "role": role},
        headers=auth(owner_token),
    )
    assert response.status_code == 201
    return captured[0]


async def _create_user_with_email(prefix: str, email: str) -> UUID:
    """Create a verified user at a specific email; return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            return user.id


async def test_accept_requires_matching_email(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accepting with a different account email returns 403."""
    del migrated_database, invitation_test_context
    owner_id = await create_user("acc-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "accmm")
    raw = await _invite(
        client, monkeypatch, org, owner_token, "target@auracles.space"
    )
    other_id = await create_user("acc-other")

    response = await client.post(
        f"/v1/org-invitations/{raw}/accept",
        headers=auth(create_access_token(other_id, [])),
    )

    assert response.status_code == 403


async def test_accept_creates_membership_once(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept joins the org; a second accept of the same token returns 409."""
    del migrated_database, invitation_test_context
    owner_id = await create_user("acc2-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "acc2")
    invitee_email = f"acc2-invitee-{uuid4().hex[:8]}@auracles.space"
    raw = await _invite(client, monkeypatch, org, owner_token, invitee_email)
    invitee_id = await _create_user_with_email("invitee", invitee_email)
    invitee_token = create_access_token(invitee_id, [])

    first = await client.post(
        f"/v1/org-invitations/{raw}/accept", headers=auth(invitee_token)
    )
    second = await client.post(
        f"/v1/org-invitations/{raw}/accept", headers=auth(invitee_token)
    )

    assert first.status_code == 200
    assert first.json()["role"] == "member"
    assert second.status_code == 409


async def test_expired_invitation_gone(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accepting an expired invitation returns 410."""
    del migrated_database, invitation_test_context
    owner_id = await create_user("exp-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "exp")
    invitee_email = f"exp-invitee-{uuid4().hex[:8]}@auracles.space"
    raw = await _invite(client, monkeypatch, org, owner_token, invitee_email)

    # Expire the invitation in the DB
    async with async_session_factory() as session:
        async with session.begin():
            invitation = await session.scalar(
                select(OrgInvitation).where(OrgInvitation.email == invitee_email)
            )
            invitation.expires_at = datetime.now(UTC) - timedelta(days=1)

    invitee_id = await _create_user_with_email("exp-invitee", invitee_email)

    response = await client.post(
        f"/v1/org-invitations/{raw}/accept",
        headers=auth(create_access_token(invitee_id, [])),
    )

    assert response.status_code == 410


async def test_decline_terminalizes(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decline flips the invite to declined; preview afterwards returns 404."""
    del migrated_database, invitation_test_context
    owner_id = await create_user("dec-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "dec")
    invitee_email = f"dec-invitee-{uuid4().hex[:8]}@auracles.space"
    raw = await _invite(client, monkeypatch, org, owner_token, invitee_email)
    invitee_id = await _create_user_with_email("dec-invitee", invitee_email)
    invitee_token = create_access_token(invitee_id, [])

    declined = await client.post(
        f"/v1/org-invitations/{raw}/decline", headers=auth(invitee_token)
    )
    # Preview after decline should return 409 (terminal status)
    preview = await client.get(
        f"/v1/org-invitations/{raw}", headers=auth(invitee_token)
    )

    assert declined.status_code == 204
    # Terminal status → 409 (known-but-terminal per the plan semantics)
    assert preview.status_code == 409


async def test_accept_when_already_member_returns_conflict(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accepting an invitation while already a member returns 409, not 500.

    A user can hold a pending invitation and already be a member (e.g. the
    invitee changed their account email to the invited address after being
    added another way). The unique membership constraint must surface as a
    conflict, never an unhandled IntegrityError.
    """
    del migrated_database, invitation_test_context
    owner_id = await create_user("dup-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "dup")
    invitee_email = f"dup-invitee-{uuid4().hex[:8]}@auracles.space"
    raw = await _invite(client, monkeypatch, org, owner_token, invitee_email)
    invitee_id = await _create_user_with_email("dup-invitee", invitee_email)
    await add_member(str(org["id"]), invitee_id, "member")

    response = await client.post(
        f"/v1/org-invitations/{raw}/accept",
        headers=auth(create_access_token(invitee_id, [])),
    )

    assert response.status_code == 409


async def test_preview_shows_org_details(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /v1/org-invitations/{token} returns org name, slug, role, expires_at."""
    del migrated_database, invitation_test_context
    owner_id = await create_user("prev-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "prev")
    invitee_email = f"prev-invitee-{uuid4().hex[:8]}@auracles.space"
    raw = await _invite(client, monkeypatch, org, owner_token, invitee_email)
    invitee_id = await _create_user_with_email("prev-invitee", invitee_email)

    response = await client.get(
        f"/v1/org-invitations/{raw}",
        headers=auth(create_access_token(invitee_id, [])),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["org_slug"] == org["slug"]
    assert body["role"] == "member"
    assert "expires_at" in body

