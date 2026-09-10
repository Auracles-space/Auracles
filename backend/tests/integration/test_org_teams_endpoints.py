"""Integration tests for Organizations Core teams CRUD endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgInvitation,
    OrgMember,
    OrgTeam,
    OrgTeamMember,
)
from app.shared.models.audit_log import AuditLog
from tests.conftest import verify_org_kyb
from tests.integration.test_auth_sessions import FakeRedis


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure application tables exist."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture(autouse=True)
def override_redis() -> Iterator[FakeRedis]:
    """Install a fake Redis for org rate limits.

    Autouse because org creation is rate-limited too, so every test in this
    file reaches Redis through the shared create-org helper, not just the ones
    that activate a capability.
    """
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    yield fake_redis
    app.dependency_overrides.pop(get_redis, None)


@pytest.fixture
async def clean_teams() -> None:
    """Remove org rows between tests."""
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(OrgTeamMember))
        await session.execute(delete(OrgTeam))
        await session.execute(delete(OrgCapability))
        await session.execute(delete(OrgInvitation))
        await session.execute(delete(OrgMember))
        await session.execute(delete(Organization))
        await session.execute(delete(AuditLog))
        await session.commit()


async def create_user(prefix: str) -> UUID:
    """Create a verified user with a unique email; return its id."""
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
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
            return user.id


def auth(token: str) -> dict[str, str]:
    """Build an Authorization header."""
    return {"Authorization": f"Bearer {token}"}


async def create_org(client: AsyncClient, token: str, prefix: str) -> dict[str, str]:
    slug = f"{prefix}-{uuid4().hex[:6]}"
    res = await client.post(
        "/v1/orgs",
        json={"slug": slug, "name": f"Org {prefix}", "country": "GB"},
        headers=auth(token),
    )
    assert res.status_code == 201
    return res.json()


async def add_member(org_id: str, user_id: UUID, role: str) -> str:
    """Directly insert an org member row for setup and return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=UUID(org_id), user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            return str(member.id)


async def test_org_removal_cascades_out_of_teams(
    client: AsyncClient, migrated_database: None, clean_teams: None
) -> None:
    """Removing a member from the org removes them from every team."""
    owner_id = await create_user("casc-owner")
    member_id = await create_user("casc-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "casc")
    member_row = await add_member(org["id"], member_id, "member")
    team = await client.post(
        f"/v1/orgs/{org['id']}/teams",
        json={"name": "Reviewers"},
        headers=auth(owner_token),
    )
    assert team.status_code == 201
    team_id = team.json()["id"]
    added = await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/members/{member_row}",
        headers=auth(owner_token),
    )
    assert added.status_code == 204

    removed = await client.delete(
        f"/v1/orgs/{org['id']}/members/{member_row}", headers=auth(owner_token)
    )

    assert removed.status_code == 204
    async with async_session_factory() as session:
        remaining = (
            await session.scalars(
                select(OrgTeamMember).where(OrgTeamMember.team_id == UUID(team_id))
            )
        ).all()
    assert remaining == []


async def test_create_team_duplicate_name_conflicts(
    client: AsyncClient, migrated_database: None, clean_teams: None
) -> None:
    """Creating a team with a name already used in the org returns 409."""
    owner_id = await create_user("team-dup")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "dup")

    res1 = await client.post(
        f"/v1/orgs/{org['id']}/teams",
        json={"name": "Engineering"},
        headers=auth(owner_token),
    )
    assert res1.status_code == 201

    res2 = await client.post(
        f"/v1/orgs/{org['id']}/teams",
        json={"name": "Engineering"},
        headers=auth(owner_token),
    )
    assert res2.status_code == 409


async def test_add_team_member_non_org_member(
    client: AsyncClient, migrated_database: None, clean_teams: None
) -> None:
    """Adding a member id that does not belong to the org returns 404."""
    owner_id = await create_user("t-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "team-non")

    team = await client.post(
        f"/v1/orgs/{org['id']}/teams", json={"name": "Sales"}, headers=auth(owner_token)
    )
    team_id = team.json()["id"]

    # Try to add a member ID that doesn't exist in the org
    random_member_id = str(uuid4())
    res = await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/members/{random_member_id}",
        headers=auth(owner_token),
    )
    assert res.status_code == 404


async def test_add_team_member_idempotent(
    client: AsyncClient, migrated_database: None, clean_teams: None
) -> None:
    """Adding the same member to a team twice returns 204 both times."""
    owner_id = await create_user("t-owner")
    member_id = await create_user("t-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "team-idem")
    member_row = await add_member(org["id"], member_id, "member")

    team = await client.post(
        f"/v1/orgs/{org['id']}/teams", json={"name": "Sales"}, headers=auth(owner_token)
    )
    team_id = team.json()["id"]

    res1 = await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/members/{member_row}",
        headers=auth(owner_token),
    )
    assert res1.status_code == 204

    res2 = await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/members/{member_row}",
        headers=auth(owner_token),
    )
    assert res2.status_code == 204


async def test_list_teams_shows_member_count(
    client: AsyncClient, migrated_database: None, clean_teams: None
) -> None:
    """Team listing includes a live member_count per team."""
    owner_id = await create_user("t-owner")
    member_id = await create_user("t-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "team-list")
    member_row = await add_member(org["id"], member_id, "member")

    team = await client.post(
        f"/v1/orgs/{org['id']}/teams", json={"name": "Sales"}, headers=auth(owner_token)
    )
    team_id = team.json()["id"]

    await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/members/{member_row}",
        headers=auth(owner_token),
    )

    res = await client.get(f"/v1/orgs/{org['id']}/teams", headers=auth(owner_token))
    assert res.status_code == 200
    teams = res.json()["teams"]
    assert len(teams) == 1
    assert teams[0]["name"] == "Sales"
    assert teams[0]["member_count"] == 1


async def test_list_team_members_returns_roster(
    client: AsyncClient, migrated_database: None, clean_teams: None
) -> None:
    """Listing a team's members returns each member added to the team."""
    owner_id = await create_user("roster-owner")
    member_id = await create_user("roster-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "roster")
    member_row = await add_member(org["id"], member_id, "member")

    team = await client.post(
        f"/v1/orgs/{org['id']}/teams", json={"name": "Ops"}, headers=auth(owner_token)
    )
    team_id = team.json()["id"]
    await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/members/{member_row}",
        headers=auth(owner_token),
    )

    res = await client.get(
        f"/v1/orgs/{org['id']}/teams/{team_id}/members", headers=auth(owner_token)
    )
    assert res.status_code == 200
    members = res.json()["members"]
    assert [m["id"] for m in members] == [member_row]
    assert members[0]["email"] is not None  # owner sees email


async def test_list_team_members_unknown_team_404(
    client: AsyncClient, migrated_database: None, clean_teams: None
) -> None:
    """Listing members of a team that does not exist returns 404."""
    owner_id = await create_user("roster-404")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "roster-404")

    res = await client.get(
        f"/v1/orgs/{org['id']}/teams/{uuid4()}/members", headers=auth(owner_token)
    )
    assert res.status_code == 404


async def test_delete_team(
    client: AsyncClient, migrated_database: None, clean_teams: None
) -> None:
    """Deleting a team returns 204 and removes it from the listing."""
    owner_id = await create_user("t-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "team-del")

    team = await client.post(
        f"/v1/orgs/{org['id']}/teams",
        json={"name": "Marketing"},
        headers=auth(owner_token),
    )
    team_id = team.json()["id"]

    res = await client.delete(
        f"/v1/orgs/{org['id']}/teams/{team_id}", headers=auth(owner_token)
    )
    assert res.status_code == 204

    list_res = await client.get(
        f"/v1/orgs/{org['id']}/teams", headers=auth(owner_token)
    )
    assert len(list_res.json()["teams"]) == 0


async def test_list_teams_includes_enabled_capabilities(
    client: AsyncClient,
    override_redis: FakeRedis,
    migrated_database: None,
    clean_teams: None,
) -> None:
    """A team's enabled capabilities appear in the teams list response."""
    del override_redis, migrated_database, clean_teams
    owner_id = await create_user("teamcaps-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "teamcaps")

    await verify_org_kyb(org['id'])
    activated = await client.post(
        f"/v1/orgs/{org['id']}/operator-capability/activate",
        headers=auth(owner_token),
    )
    assert activated.status_code == 200

    team_resp = await client.post(
        f"/v1/orgs/{org['id']}/teams",
        headers=auth(owner_token),
        json={"name": "Sellers"},
    )
    assert team_resp.status_code == 201
    team_id = team_resp.json()["id"]

    enabled = await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/capabilities/operator",
        headers=auth(owner_token),
    )
    assert enabled.status_code == 204

    listing = await client.get(f"/v1/orgs/{org['id']}/teams", headers=auth(owner_token))
    assert listing.status_code == 200
    teams = listing.json()["teams"]
    sellers = next(team for team in teams if team["id"] == team_id)
    assert sellers["capabilities"] == ["operator"]
