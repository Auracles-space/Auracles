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
from app.shared.models.audit_log import AuditLog


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
        await session.execute(delete(AuditLog))
        await session.execute(delete(User))
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
