"""Integration tests for admin orgs endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.core.redis import get_redis
from app.core.security import create_access_token
from app.main import app
from tests.integration.test_auth_sessions import FakeRedis
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
    """Install a fake Redis for endpoints resolved through get_redis."""
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    yield fake_redis
    app.dependency_overrides.pop(get_redis, None)


async def create_platform_admin() -> tuple[UUID, dict[str, str]]:
    """Create a platform admin and return their headers."""
    admin_id = await create_user("admin")
    token = create_access_token(admin_id, ["admin"])
    return admin_id, auth(token)


async def test_admin_list_orgs_unauthorized(
    client: AsyncClient, clean_orgs: None, migrated_database: None
) -> None:
    """Non-admins receive 403 Forbidden."""
    user_id = await create_user("user")
    token = create_access_token(user_id, [])
    headers = auth(token)

    res = await client.get("/v1/admin/orgs", headers=headers)
    assert res.status_code == 403


async def test_admin_list_orgs(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """Admin can list orgs and see member counts and capabilities."""
    admin_id, admin_headers = await create_platform_admin()

    owner_id = await create_user("owner")
    owner_token = create_access_token(owner_id, [])

    org = await create_org(client, owner_token, "testorg")
    org_id = org["id"]

    member_id = await create_user("member")
    await add_member(org_id, member_id, "member")

    res = await client.get("/v1/admin/orgs", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1

    found_org = next((o for o in data["orgs"] if o["id"] == org_id), None)
    assert found_org is not None
    assert found_org["name"] == "testorg"
    assert found_org["member_count"] == 2
    assert "can_attest" not in found_org["capabilities"]


async def test_admin_suspend_org(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """Suspending an org returns 204 and blocks org-admin actions."""
    admin_id, admin_headers = await create_platform_admin()

    owner_id = await create_user("owner")
    owner_token = create_access_token(owner_id, [])

    org = await create_org(client, owner_token, "targetorg")
    org_id = org["id"]

    res = await client.post(f"/v1/admin/orgs/{org_id}/suspend", headers=admin_headers)
    assert res.status_code == 204

    res2 = await client.post(f"/v1/admin/orgs/{org_id}/suspend", headers=admin_headers)
    assert res2.status_code == 204

    patch_res = await client.patch(
        f"/v1/orgs/{org_id}", json={"name": "New Name"}, headers=auth(owner_token)
    )
    assert patch_res.status_code == 403
    assert patch_res.json()["detail"]["error_code"] == "org_suspended"


async def test_admin_list_orgs_reports_total_on_empty_page(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """A page beyond the last result still reports the true total count."""
    del override_redis
    _admin_id, admin_headers = await create_platform_admin()
    owner_id = await create_user("pg-owner")
    await create_org(client, create_access_token(owner_id, []), "pgorg")

    res = await client.get("/v1/admin/orgs?page=2&page_size=20", headers=admin_headers)

    assert res.status_code == 200
    data = res.json()
    assert data["orgs"] == []
    assert data["total"] == 1
    assert data["page"] == 2


async def test_admin_suspend_org_syncs_derived_roles_for_members(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Suspension re-evaluates derived roles for every org member."""
    del override_redis
    from app.modules.organizations import service as org_service

    synced: list[UUID] = []

    async def record_sync(db: object, *, user_id: UUID) -> None:
        """Record which user ids the suspension path syncs."""
        del db
        synced.append(user_id)

    monkeypatch.setattr(org_service, "sync_derived_roles", record_sync)
    _admin_id, admin_headers = await create_platform_admin()
    owner_id = await create_user("sync-owner")
    member_id = await create_user("sync-member")
    org = await create_org(client, create_access_token(owner_id, []), "syncorg")
    await add_member(str(org["id"]), member_id, "member")

    res = await client.post(
        f"/v1/admin/orgs/{org['id']}/suspend", headers=admin_headers
    )

    assert res.status_code == 204
    assert sorted(synced) == sorted([owner_id, member_id])
