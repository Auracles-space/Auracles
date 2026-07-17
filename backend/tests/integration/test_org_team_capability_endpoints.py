"""Integration tests for team-capability enable/disable endpoints."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.modules.auth.models import UserRole
from app.modules.organizations.models import OrgCapability
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


async def _create_team(client: AsyncClient, *, org_id: str, token: str, name: str) -> str:
    """Create one team through the public org teams endpoint."""
    response = await client.post(
        f"/v1/orgs/{org_id}/teams",
        json={"name": name},
        headers=auth(token),
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _activate_org_capability(org_id: str, capability: str) -> None:
    """Persist one active org capability row for integration setup."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=UUID(org_id),
                    capability=capability,
                    status="active",
                )
            )


async def test_enable_then_disable_team_capability_grants_and_revokes(
    client: AsyncClient,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """Enabling grants a team member the role; disabling revokes it."""
    del clean_orgs, migrated_database
    owner_id = await create_user("owner")
    member_id = await create_user("member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "team-cap-flow")
    member_row_id = await add_member(str(org["id"]), member_id, "member")
    team_id = await _create_team(
        client,
        org_id=str(org["id"]),
        token=owner_token,
        name="Operators",
    )
    added = await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/members/{member_row_id}",
        headers=auth(owner_token),
    )
    assert added.status_code == 204

    await _activate_org_capability(str(org["id"]), "operator")

    enabled = await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/capabilities/operator",
        headers=auth(owner_token),
    )
    assert enabled.status_code == 204

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member_id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        )
    assert role is not None

    disabled = await client.delete(
        f"/v1/orgs/{org['id']}/teams/{team_id}/capabilities/operator",
        headers=auth(owner_token),
    )
    assert disabled.status_code == 204

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member_id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        )
    assert role is None


async def test_enable_team_capability_requires_admin_and_active_org_capability(
    client: AsyncClient,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """Only org admins can enable, and the org capability must be active."""
    del clean_orgs, migrated_database
    owner_id = await create_user("owner")
    member_id = await create_user("member")
    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "team-cap-guard")
    await add_member(str(org["id"]), member_id, "member")
    team_id = await _create_team(
        client,
        org_id=str(org["id"]),
        token=owner_token,
        name="Operators",
    )

    forbidden = await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/capabilities/operator",
        headers=auth(member_token),
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["error_code"] == "org_role_required"

    inactive = await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/capabilities/operator",
        headers=auth(owner_token),
    )
    assert inactive.status_code == 422
    assert inactive.json()["detail"] == "Activate this capability for the organization first."


async def test_team_capability_unknown_value_returns_422(
    client: AsyncClient,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """Unknown capability path values are rejected by validation."""
    del clean_orgs, migrated_database
    owner_id = await create_user("owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "team-cap-unknown")
    team_id = await _create_team(
        client,
        org_id=str(org["id"]),
        token=owner_token,
        name="Operators",
    )

    response = await client.put(
        f"/v1/orgs/{org['id']}/teams/{team_id}/capabilities/not-a-capability",
        headers=auth(owner_token),
    )

    assert response.status_code == 422


async def test_team_capability_team_not_found_returns_404(
    client: AsyncClient,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """Enabling on a team outside the org returns 404."""
    del clean_orgs, migrated_database
    owner_id = await create_user("owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "team-cap-missing")

    await _activate_org_capability(str(org["id"]), "operator")

    response = await client.put(
        f"/v1/orgs/{org['id']}/teams/{uuid4()}/capabilities/operator",
        headers=auth(owner_token),
    )

    assert response.status_code == 404
