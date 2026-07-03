"""Integration tests for Organizations Core org CRUD endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import User
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgMember,
)
from tests.support.db_cleanup import clear_identity_state_async


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure application tables exist."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def clean_orgs() -> None:
    """Remove org rows between tests."""
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(OrgCapability))
        await session.execute(delete(OrgMember))
        await session.execute(delete(Organization))
        await clear_identity_state_async(session)
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


async def create_org(client: AsyncClient, token: str, prefix: str) -> dict[str, object]:
    """Create an org via the API; return the response body."""
    response = await client.post(
        "/v1/orgs",
        json={"slug": f"{prefix}-{uuid4().hex[:6]}", "name": prefix, "country": "GB"},
        headers=auth(token),
    )
    assert response.status_code == 201
    return dict(response.json())


async def test_create_org_seeds_owner_membership(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """POST /v1/orgs creates the org and seeds the creator as owner."""
    del migrated_database, clean_orgs
    user_id = await create_user("org-create")
    token = create_access_token(user_id, [])
    slug = f"acme-{uuid4().hex[:6]}"

    response = await client.post(
        "/v1/orgs",
        json={"slug": slug, "name": "Acme Compliance", "country": "GB"},
        headers=auth(token),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == slug
    async with async_session_factory() as session:
        member = await session.scalar(
            select(OrgMember).where(
                OrgMember.org_id == UUID(body["id"]),
                OrgMember.user_id == user_id,
            )
        )
    assert member is not None and member.role == "owner"


async def test_create_org_duplicate_slug_conflicts(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """Reusing a slug returns 409."""
    del migrated_database, clean_orgs
    user_id = await create_user("org-dup")
    token = create_access_token(user_id, [])
    slug = f"dup-{uuid4().hex[:6]}"

    first = await client.post(
        "/v1/orgs",
        json={"slug": slug, "name": "First", "country": "GB"},
        headers=auth(token),
    )
    assert first.status_code == 201

    second = await client.post(
        "/v1/orgs",
        json={"slug": slug.upper(), "name": "Second", "country": "GB"},
        headers=auth(token),
    )

    assert second.status_code == 409


async def test_create_org_requires_auth(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """Unauthenticated create returns 401."""
    del migrated_database, clean_orgs
    response = await client.post(
        "/v1/orgs",
        json={"slug": "nope", "name": "Nope", "country": "GB"},
    )
    assert response.status_code == 401


async def test_list_my_orgs_returns_role_and_capabilities(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """GET /v1/orgs/mine lists my orgs with role and capability statuses."""
    del migrated_database, clean_orgs
    user_id = await create_user("org-mine")
    token = create_access_token(user_id, [])
    created = await client.post(
        "/v1/orgs",
        json={"slug": f"mine-{uuid4().hex[:6]}", "name": "Mine", "country": "NG"},
        headers=auth(token),
    )
    org_id = UUID(created.json()["id"])
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(org_id=org_id, capability="attestor", status="pending")
            )

    response = await client.get("/v1/orgs/mine", headers=auth(token))

    assert response.status_code == 200
    orgs = response.json()["organizations"]
    assert len(orgs) == 1
    assert orgs[0]["role"] == "owner"
    assert orgs[0]["capabilities"] == {"attestor": "pending"}


async def test_public_org_profile_exposes_no_members(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """GET /v1/orgs/{slug} is public and returns no member PII."""
    del migrated_database, clean_orgs
    user_id = await create_user("org-public")
    token = create_access_token(user_id, [])
    org = await create_org(client, token, "pub")

    response = await client.get(f"/v1/orgs/{org['slug']}")

    assert response.status_code == 200
    body = response.json()
    assert body["member_count"] == 1
    assert body["active_capabilities"] == []
    assert "members" not in body and "email" not in str(body)


async def test_update_org_requires_admin(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """PATCH /v1/orgs/{org_id} is admin+; a plain member gets 403."""
    del migrated_database, clean_orgs
    owner_id = await create_user("org-upd-owner")
    member_id = await create_user("org-upd-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "upd")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgMember(org_id=UUID(str(org["id"])), user_id=member_id, role="member")
            )

    member_token = create_access_token(member_id, [])
    denied = await client.patch(
        f"/v1/orgs/{org['id']}",
        json={"name": "New"},
        headers=auth(member_token),
    )
    allowed = await client.patch(
        f"/v1/orgs/{org['id']}",
        json={"name": "New"},
        headers=auth(owner_token),
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["name"] == "New"


async def test_deactivate_blocked_while_capability_active(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """DELETE /v1/orgs/{org_id} returns 409 while any capability is active."""
    del migrated_database, clean_orgs
    owner_id = await create_user("org-deact")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "deact")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=UUID(str(org["id"])),
                    capability="attestor",
                    status="active",
                )
            )

    blocked = await client.delete(f"/v1/orgs/{org['id']}", headers=auth(token))

    assert blocked.status_code == 409


async def test_deactivate_owner_only(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """DELETE /v1/orgs/{org_id} requires the owner role; admin gets 403."""
    del migrated_database, clean_orgs
    owner_id = await create_user("org-deact-owner")
    admin_id = await create_user("org-deact-admin")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "downer")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgMember(org_id=UUID(str(org["id"])), user_id=admin_id, role="admin")
            )

    denied = await client.delete(
        f"/v1/orgs/{org['id']}",
        headers=auth(create_access_token(admin_id, [])),
    )
    allowed = await client.delete(f"/v1/orgs/{org['id']}", headers=auth(owner_token))

    assert denied.status_code == 403
    assert allowed.status_code == 204
