"""Integration tests for org contributor capability activation endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.database import async_session_factory
from app.core.redis import get_redis
from app.core.security import create_access_token
from app.main import app
from app.modules.auth.models import UserRole
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgContributorProfile,
)
from tests.integration.test_auth_sessions import FakeRedis
from tests.integration.test_org_admin_endpoints import create_platform_admin
from tests.integration.test_organizations_endpoints import (
    add_member,
    auth,
    clean_orgs,
    create_org,
    create_user,
    migrated_database,
)

pytestmark = pytest.mark.asyncio
__all__ = ["clean_orgs", "migrated_database"]


@pytest.fixture
def override_redis() -> Iterator[FakeRedis]:
    """Install a fake Redis for contributor capability rate limits."""
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    yield fake_redis
    app.dependency_overrides.pop(get_redis, None)


async def test_activate_contributor_capability_happy_path(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """An org owner can activate contributor capability and grant member roles."""
    del override_redis, clean_orgs, migrated_database
    owner_id = await create_user("owner")
    member_id = await create_user("member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "contributor-org")
    await add_member(str(org["id"]), member_id, "member")

    response = await client.post(
        f"/v1/orgs/{org['id']}/contributor-capability/activate",
        headers=auth(owner_token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["org_id"] == org["id"]
    assert body["capability"] == "contributor"
    assert body["status"] == "active"

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member_id,
                UserRole.role == "contributor",
                UserRole.source == "derived",
            )
        )
    assert role is not None


async def test_activate_contributor_capability_requires_auth_and_admin_role(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """Activation returns 401 anonymously and 403 for a plain org member."""
    del override_redis, clean_orgs, migrated_database
    owner_id = await create_user("owner")
    member_id = await create_user("member")
    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "contributor-org")
    await add_member(str(org["id"]), member_id, "member")

    unauthenticated = await client.post(
        f"/v1/orgs/{org['id']}/contributor-capability/activate"
    )
    forbidden = await client.post(
        f"/v1/orgs/{org['id']}/contributor-capability/activate",
        headers=auth(member_token),
    )

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["error_code"] == "org_role_required"


async def test_activate_contributor_capability_rejects_suspended_org(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """Activation returns 403 when the org has already been suspended."""
    del override_redis, clean_orgs, migrated_database
    owner_id = await create_user("owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "contributor-org")

    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Organization)
                .where(Organization.id == UUID(str(org["id"])))
                .values(suspended_at=datetime.now(UTC))
            )

    response = await client.post(
        f"/v1/orgs/{org['id']}/contributor-capability/activate",
        headers=auth(owner_token),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "org_suspended"


async def test_admin_contributor_capability_status_routes(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """Platform admins can suspend, reinstate, and revoke contributor capability."""
    del override_redis, clean_orgs, migrated_database
    _platform_admin_id, admin_headers = await create_platform_admin()
    plain_user_id = await create_user("plain-user")
    plain_headers = auth(create_access_token(plain_user_id, []))
    owner_id = await create_user("owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "contributor-org")

    activated = await client.post(
        f"/v1/orgs/{org['id']}/contributor-capability/activate",
        headers=auth(owner_token),
    )
    assert activated.status_code == 200

    suspend_unauthenticated = await client.post(
        f"/v1/admin/orgs/{org['id']}/contributor-capability/suspend"
    )
    suspend_forbidden = await client.post(
        f"/v1/admin/orgs/{org['id']}/contributor-capability/suspend",
        headers=plain_headers,
    )
    suspended = await client.post(
        f"/v1/admin/orgs/{org['id']}/contributor-capability/suspend",
        headers=admin_headers,
    )
    reinstated = await client.post(
        f"/v1/admin/orgs/{org['id']}/contributor-capability/reinstate",
        headers=admin_headers,
    )
    revoked = await client.post(
        f"/v1/admin/orgs/{org['id']}/contributor-capability/revoke",
        headers=admin_headers,
    )

    assert suspend_unauthenticated.status_code == 401
    assert suspend_forbidden.status_code == 403
    assert suspended.status_code == 204
    assert reinstated.status_code == 204
    assert revoked.status_code == 204

    async with async_session_factory() as session:
        capability = await session.scalar(
            select(OrgCapability).where(
                OrgCapability.org_id == UUID(str(org["id"])),
                OrgCapability.capability == "contributor",
            )
        )
        profile = await session.scalar(
            select(OrgContributorProfile).where(
                OrgContributorProfile.org_id == UUID(str(org["id"]))
            )
        )

    assert capability is not None
    assert capability.status == "revoked"
    assert profile is not None
    assert profile.active is False
