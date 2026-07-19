"""Integration tests for organization-operated Project posting endpoints.

Covers ``POST /v1/orgs/{org_id}/projects`` and ``GET /v1/orgs/{org_id}/projects``
plus the org-level self-deal bid guard, reusing the organization Project
fixtures.

Maps to: Task 6 in docs/superpowers/specs/2026-07-10-org-operator-design.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from app.modules.projects.models import Deliverable, Milestone, Project, Proposal
from app.shared.models.audit_log import AuditLog
from tests.integration.test_org_proposal_endpoints import (
    _activate_contributor_capability,
    _org_proposal_payload,
    _project_payload,
    create_user_with_roles,
)
from tests.integration.test_organizations_endpoints import (
    add_member,
    auth,
    create_org,
    create_user,
    migrated_database,
)
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio
__all__ = ["migrated_database"]


@pytest.fixture
async def org_project_context() -> AsyncIterator[None]:
    """Reset Project and org rows around org Project posting tests."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete Project and org rows in dependency order."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(Deliverable))
            await session.execute(delete(Milestone))
            await session.execute(delete(Proposal))
            await session.execute(delete(Project))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _activate_operator_capability(
    org_id: str,
    *,
    status: str = "active",
) -> None:
    """Persist one operator capability row for an organization."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=UUID(org_id),
                    capability="operator",
                    status=status,
                )
            )


def _post_project(client: AsyncClient, org_id: str, token: str | None) -> Any:
    """Post an org Project with optional auth headers."""
    headers = auth(token) if token is not None else {}
    return client.post(
        f"/v1/orgs/{org_id}/projects",
        headers=headers,
        json=_project_payload(),
    )


async def test_org_admin_can_post_project_under_org_identity(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """An org owner can post a Project owned by the organization."""
    del migrated_database, org_project_context
    owner_id = await create_user("owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "operator-org")
    await _activate_operator_capability(str(org["id"]))

    response = await _post_project(client, str(org["id"]), owner_token)

    assert response.status_code == 201
    body = response.json()
    assert body["operator_id"] is None
    assert body["operator_org_id"] == str(org["id"])
    assert body["operator_name"] == org["name"]
    assert "posting_member_id" not in body

    async with async_session_factory() as session:
        project = await session.get(Project, UUID(body["id"]))
        assert project is not None
        assert project.operator_id is None
        assert project.operator_org_id == UUID(str(org["id"]))
        assert project.posting_member_id is not None


async def test_org_project_post_requires_authentication(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """Org Project posting is authentication-gated."""
    del migrated_database, org_project_context
    owner_id = await create_user("owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "operator-org-auth")
    await _activate_operator_capability(str(org["id"]))

    response = await _post_project(client, str(org["id"]), None)

    assert response.status_code == 401


async def test_org_project_post_forbidden_for_plain_member(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """A plain org member cannot post an org Project."""
    del migrated_database, org_project_context
    owner_id = await create_user("owner")
    member_id = await create_user("member")
    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "operator-org-member")
    await add_member(str(org["id"]), member_id, "member")
    await _activate_operator_capability(str(org["id"]))

    response = await _post_project(client, str(org["id"]), member_token)

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "org_role_required"


async def test_org_project_post_forbidden_when_capability_inactive(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """Posting an org Project requires an active operator capability."""
    del migrated_database, org_project_context
    owner_id = await create_user("owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "operator-org-nocap")

    response = await _post_project(client, str(org["id"]), owner_token)

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "capability_required"


async def test_org_admin_can_list_org_projects(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """An org owner can list the organization's operated Projects."""
    del migrated_database, org_project_context
    owner_id = await create_user("owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "operator-org-list")
    await _activate_operator_capability(str(org["id"]))

    created = await _post_project(client, str(org["id"]), owner_token)
    assert created.status_code == 201

    response = await client.get(
        f"/v1/orgs/{org['id']}/projects",
        headers=auth(owner_token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["projects"][0]["operator_org_id"] == str(org["id"])
    assert body["projects"][0]["operator_name"] == org["name"]


async def test_org_admin_can_get_owned_project_but_not_cross_org_project(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """Org project detail is available only inside its operator org namespace."""
    del migrated_database, org_project_context
    owner_id = await create_user("detail-owner")
    other_owner_id = await create_user("detail-other-owner")
    owner_token = create_access_token(owner_id, [])
    other_owner_token = create_access_token(other_owner_id, [])
    org = await create_org(client, owner_token, "operator-org-detail")
    other_org = await create_org(
        client,
        other_owner_token,
        "operator-org-detail-other",
    )
    await _activate_operator_capability(str(org["id"]))
    await _activate_operator_capability(str(other_org["id"]))
    created = await _post_project(client, str(org["id"]), owner_token)
    assert created.status_code == 201
    project_id = created.json()["id"]

    owned = await client.get(
        f"/v1/orgs/{org['id']}/projects/{project_id}",
        headers=auth(owner_token),
    )
    cross_org = await client.get(
        f"/v1/orgs/{other_org['id']}/projects/{project_id}",
        headers=auth(other_owner_token),
    )

    assert owned.status_code == 200
    assert owned.json()["operator_org_id"] == str(org["id"])
    assert cross_org.status_code == 404


async def test_org_owner_soft_deletes_untouched_open_project(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """An org owner can hide an uncommenced Project from org reads."""
    del migrated_database, org_project_context
    owner_id = await create_user("delete-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "operator-org-delete")
    await _activate_operator_capability(str(org["id"]))
    created = await _post_project(client, str(org["id"]), owner_token)
    project_id = created.json()["id"]

    deleted = await client.delete(
        f"/v1/orgs/{org['id']}/projects/{project_id}",
        headers=auth(owner_token),
    )

    assert deleted.status_code == 204
    detail = await client.get(
        f"/v1/orgs/{org['id']}/projects/{project_id}",
        headers=auth(owner_token),
    )
    assert detail.status_code == 404
    listing = await client.get(
        f"/v1/orgs/{org['id']}/projects",
        headers=auth(owner_token),
    )
    assert listing.status_code == 200
    assert listing.json()["projects"] == []


async def test_org_project_list_forbidden_for_plain_member(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """A plain org member cannot list org Projects."""
    del migrated_database, org_project_context
    owner_id = await create_user("owner")
    member_id = await create_user("member")
    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "operator-org-list-member")
    await add_member(str(org["id"]), member_id, "member")
    await _activate_operator_capability(str(org["id"]))

    response = await client.get(
        f"/v1/orgs/{org['id']}/projects",
        headers=auth(member_token),
    )

    assert response.status_code == 403


async def test_org_cannot_bid_on_its_own_operated_project(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """An org's Contributor arm cannot bid on its own Operator arm's Project."""
    del migrated_database, org_project_context
    owner_id = await create_user("owner")
    delivery_user_id = await create_user_with_roles("delivery", [])
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "operator-org-selfdeal")
    delivering_member_id = await add_member(
        str(org["id"]), delivery_user_id, "member"
    )
    await _activate_operator_capability(str(org["id"]))
    await _activate_contributor_capability(str(org["id"]))

    created = await _post_project(client, str(org["id"]), owner_token)
    assert created.status_code == 201
    project_id = created.json()["id"]

    response = await client.post(
        f"/v1/orgs/{org['id']}/projects/{project_id}/proposals",
        headers=auth(owner_token),
        json=_org_proposal_payload(delivering_member_id),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "self_deal_conflict"
