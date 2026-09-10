"""Integration tests for organization-scoped Project proposal endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from app.modules.projects.models import Deliverable, Milestone, Project, Proposal
from app.shared.models.audit_log import AuditLog
from tests.integration.test_auth_sessions import FakeRedis
from tests.integration.test_organizations_endpoints import (
    add_member,
    auth,
    create_org,
    migrated_database,
)
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio
__all__ = ["migrated_database"]


@pytest.fixture
async def org_project_context() -> AsyncIterator[None]:
    """Reset Project and org rows around org Project endpoint tests."""
    # Org creation is rate-limited, so the endpoint reaches Redis. A fake
    # keeps the counter in-process and per-test rather than leaking a real
    # one across the suite, where a later test would start throttled.
    _fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: _fake_redis
    await engine.dispose()

    async def cleanup() -> None:
        """Delete Project and org rows in dependency order."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(Deliverable))
            await session.execute(delete(Milestone))
            await session.execute(delete(Project))
            await session.execute(delete(Proposal))
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


async def create_user_with_roles(prefix: str, roles: list[str]) -> UUID:
    """Create a verified user with approved roles and return its id."""
    email = f"{prefix}-{datetime.now(UTC).timestamp()}@auracles.space"
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
                kyc_status="verified",
            )
            session.add(user)
            await session.flush()
            for role in roles:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        source="self",
                        approved_at=datetime.now(UTC),
                    )
                )
            return user.id


async def _activate_contributor_capability(
    org_id: str,
    *,
    status: str = "active",
) -> None:
    """Persist one contributor capability row for an organization."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=UUID(org_id),
                    capability="contributor",
                    status=status,
                )
            )


async def _accept_proposal(proposal_id: str, project_id: str) -> None:
    """Mark a Proposal accepted and attach it to its Project."""
    async with async_session_factory() as session:
        async with session.begin():
            proposal = await session.get(Proposal, UUID(proposal_id))
            project = await session.get(Project, UUID(project_id))
            assert proposal is not None and project is not None
            proposal.status = "accepted"
            proposal.accepted_at = datetime.now(UTC)
            project.accepted_proposal_id = proposal.id
            project.status = "assigned"


def _project_payload() -> dict[str, Any]:
    """Return a valid Project create payload."""
    return {
        "title": "Procurement Playbook",
        "description": "Build a procurement operating model.",
        "category": "operations",
        "required_deliverables": [
            {"name": "Playbook", "description": "Implementation guide"}
        ],
        "budget_min": "1000.00",
        "budget_max": "2000.00",
        "currency": "USD",
        # Relative to today: the API rejects a deadline in the past, so a
        # literal date passes only until it elapses.
        "deadline": (date.today() + timedelta(days=30)).isoformat(),
    }


def _org_proposal_payload(delivering_member_id: UUID) -> dict[str, Any]:
    """Return a valid org Proposal submit payload."""
    return {
        "delivering_member_id": str(delivering_member_id),
        "scope": "I will deliver the procurement model and rollout plan.",
        "budget": "1500.00",
        "timeline_days": 21,
        "deliverables": [
            {"name": "Operating model", "description": "Documented model"}
        ],
    }


async def test_org_admin_can_submit_proposal_under_org_identity(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """An org admin can submit a Proposal that is owned by the organization."""
    del migrated_database, org_project_context
    operator_id = await create_user_with_roles("project-operator", ["operator"])
    owner_id = await create_user_with_roles("project-owner", [])
    delivery_user_id = await create_user_with_roles("project-delivery", [])

    owner_token = create_access_token(owner_id, [])

    created_project = await client.post(
        "/v1/projects",
        headers=auth(create_access_token(operator_id, ["operator"])),
        json=_project_payload(),
    )
    assert created_project.status_code == 201
    project_id = created_project.json()["id"]

    org = await create_org(client, owner_token, "org-project")
    delivering_member_id = await add_member(str(org["id"]), delivery_user_id, "member")
    await _activate_contributor_capability(str(org["id"]))

    response = await client.post(
        f"/v1/orgs/{org['id']}/projects/{project_id}/proposals",
        headers=auth(owner_token),
        json=_org_proposal_payload(delivering_member_id),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["contributor_id"] is None
    assert body["contributor_org_id"] == str(org["id"])

    async with async_session_factory() as session:
        proposal = await session.get(Proposal, UUID(body["id"]))
        assert proposal is not None
        assert proposal.contributor_id is None
        assert proposal.contributor_org_id == UUID(str(org["id"]))


async def test_org_admin_can_reassign_staffed_member_before_work_starts(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """An org admin can reassign the staffed delivery member before work starts."""
    del migrated_database, org_project_context
    operator_id = await create_user_with_roles("project-operator", ["operator"])
    owner_id = await create_user_with_roles("project-owner", [])
    first_delivery_user_id = await create_user_with_roles("project-delivery-one", [])
    second_delivery_user_id = await create_user_with_roles("project-delivery-two", [])

    owner_token = create_access_token(owner_id, [])
    created_project = await client.post(
        "/v1/projects",
        headers=auth(create_access_token(operator_id, ["operator"])),
        json=_project_payload(),
    )
    assert created_project.status_code == 201
    project_id = created_project.json()["id"]

    org = await create_org(client, owner_token, "org-project-reassign")
    first_member_id = await add_member(str(org["id"]), first_delivery_user_id, "member")
    second_member_id = await add_member(
        str(org["id"]), second_delivery_user_id, "member"
    )
    await _activate_contributor_capability(str(org["id"]))

    submitted = await client.post(
        f"/v1/orgs/{org['id']}/projects/{project_id}/proposals",
        headers=auth(owner_token),
        json=_org_proposal_payload(first_member_id),
    )
    assert submitted.status_code == 201
    proposal_id = submitted.json()["id"]
    await _accept_proposal(proposal_id, project_id)

    response = await client.post(
        f"/v1/orgs/{org['id']}/proposals/{proposal_id}/reassign",
        headers=auth(owner_token),
        json={"delivering_member_id": str(second_member_id)},
    )

    assert response.status_code == 200
    async with async_session_factory() as session:
        proposal = await session.get(Proposal, UUID(proposal_id))
        assert proposal is not None
        assert proposal.delivering_member_id == second_member_id


async def test_org_admin_can_withdraw_pending_proposal(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """An org admin can withdraw a pending organization Proposal."""
    del migrated_database, org_project_context
    operator_id = await create_user_with_roles("project-operator", ["operator"])
    owner_id = await create_user_with_roles("project-owner", [])
    delivery_user_id = await create_user_with_roles("project-delivery", [])

    owner_token = create_access_token(owner_id, [])
    created_project = await client.post(
        "/v1/projects",
        headers=auth(create_access_token(operator_id, ["operator"])),
        json=_project_payload(),
    )
    assert created_project.status_code == 201
    project_id = created_project.json()["id"]

    org = await create_org(client, owner_token, "org-project-withdraw")
    delivering_member_id = await add_member(str(org["id"]), delivery_user_id, "member")
    await _activate_contributor_capability(str(org["id"]))

    submitted = await client.post(
        f"/v1/orgs/{org['id']}/projects/{project_id}/proposals",
        headers=auth(owner_token),
        json=_org_proposal_payload(delivering_member_id),
    )
    assert submitted.status_code == 201
    proposal_id = submitted.json()["id"]

    response = await client.delete(
        f"/v1/orgs/{org['id']}/proposals/{proposal_id}",
        headers=auth(owner_token),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "withdrawn"
    async with async_session_factory() as session:
        proposal = await session.get(Proposal, UUID(proposal_id))
        assert proposal is not None
        assert proposal.status == "withdrawn"


async def test_org_member_cannot_submit_or_reassign_proposals(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """Plain members cannot submit or reassign org Proposals."""
    del migrated_database, org_project_context
    operator_id = await create_user_with_roles("project-operator", ["operator"])
    owner_id = await create_user_with_roles("project-owner", [])
    member_id = await create_user_with_roles("project-member", [])
    other_member_id = await create_user_with_roles("project-other-member", [])

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    created_project = await client.post(
        "/v1/projects",
        headers=auth(create_access_token(operator_id, ["operator"])),
        json=_project_payload(),
    )
    assert created_project.status_code == 201
    project_id = created_project.json()["id"]

    org = await create_org(client, owner_token, "org-project-member-guards")
    member_row_id = await add_member(str(org["id"]), member_id, "member")
    other_member_row_id = await add_member(str(org["id"]), other_member_id, "member")
    await _activate_contributor_capability(str(org["id"]))

    submit_forbidden = await client.post(
        f"/v1/orgs/{org['id']}/projects/{project_id}/proposals",
        headers=auth(member_token),
        json=_org_proposal_payload(member_row_id),
    )

    submitted = await client.post(
        f"/v1/orgs/{org['id']}/projects/{project_id}/proposals",
        headers=auth(owner_token),
        json=_org_proposal_payload(member_row_id),
    )
    assert submitted.status_code == 201
    proposal_id = submitted.json()["id"]
    await _accept_proposal(proposal_id, project_id)

    reassign_forbidden = await client.post(
        f"/v1/orgs/{org['id']}/proposals/{proposal_id}/reassign",
        headers=auth(member_token),
        json={"delivering_member_id": str(other_member_row_id)},
    )

    assert submit_forbidden.status_code == 403
    assert reassign_forbidden.status_code == 403


async def test_suspended_capability_blocks_org_proposal_submit(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """Suspended contributor capability blocks new org Proposals."""
    del migrated_database, org_project_context
    operator_id = await create_user_with_roles("project-operator", ["operator"])
    owner_id = await create_user_with_roles("project-owner", [])
    delivery_user_id = await create_user_with_roles("project-delivery", [])

    owner_token = create_access_token(owner_id, [])
    created_project = await client.post(
        "/v1/projects",
        headers=auth(create_access_token(operator_id, ["operator"])),
        json=_project_payload(),
    )
    assert created_project.status_code == 201
    project_id = created_project.json()["id"]

    org = await create_org(client, owner_token, "org-project-suspended")
    delivering_member_id = await add_member(str(org["id"]), delivery_user_id, "member")
    await _activate_contributor_capability(str(org["id"]), status="suspended")

    response = await client.post(
        f"/v1/orgs/{org['id']}/projects/{project_id}/proposals",
        headers=auth(owner_token),
        json=_org_proposal_payload(delivering_member_id),
    )

    assert response.status_code == 403


async def test_org_deliveries_lists_all_for_admin_and_only_own_for_member(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """Deliveries list scopes accepted work to admin-all or member-own views."""
    del migrated_database, org_project_context
    operator_id = await create_user_with_roles("project-operator", ["operator"])
    owner_id = await create_user_with_roles("project-owner", [])
    first_member_user_id = await create_user_with_roles("project-delivery-one", [])
    second_member_user_id = await create_user_with_roles("project-delivery-two", [])

    owner_token = create_access_token(owner_id, [])
    first_member_token = create_access_token(first_member_user_id, [])

    first_project = await client.post(
        "/v1/projects",
        headers=auth(create_access_token(operator_id, ["operator"])),
        json=_project_payload(),
    )
    second_project = await client.post(
        "/v1/projects",
        headers=auth(create_access_token(operator_id, ["operator"])),
        json={
            **_project_payload(),
            "title": "Second procurement playbook",
        },
    )
    assert first_project.status_code == 201
    assert second_project.status_code == 201

    org = await create_org(client, owner_token, "org-project-deliveries")
    first_member_id = await add_member(str(org["id"]), first_member_user_id, "member")
    second_member_id = await add_member(str(org["id"]), second_member_user_id, "member")
    await _activate_contributor_capability(str(org["id"]))

    first_submitted = await client.post(
        f"/v1/orgs/{org['id']}/projects/{first_project.json()['id']}/proposals",
        headers=auth(owner_token),
        json=_org_proposal_payload(first_member_id),
    )
    second_submitted = await client.post(
        f"/v1/orgs/{org['id']}/projects/{second_project.json()['id']}/proposals",
        headers=auth(owner_token),
        json=_org_proposal_payload(second_member_id),
    )
    assert first_submitted.status_code == 201
    assert second_submitted.status_code == 201
    await _accept_proposal(first_submitted.json()["id"], first_project.json()["id"])
    await _accept_proposal(second_submitted.json()["id"], second_project.json()["id"])

    admin_view = await client.get(
        f"/v1/orgs/{org['id']}/deliveries",
        headers=auth(owner_token),
    )
    member_view = await client.get(
        f"/v1/orgs/{org['id']}/deliveries",
        headers=auth(first_member_token),
    )

    assert admin_view.status_code == 200
    assert member_view.status_code == 200
    assert len(admin_view.json()["deliveries"]) == 2
    assert len(member_view.json()["deliveries"]) == 1
    assert (
        member_view.json()["deliveries"][0]["proposal_id"]
        == first_submitted.json()["id"]
    )


async def test_org_proposal_submit_requires_authentication(
    client: AsyncClient,
    migrated_database: None,
    org_project_context: None,
) -> None:
    """Org proposal submission is authentication-gated."""
    del migrated_database, org_project_context
    operator_id = await create_user_with_roles("project-operator", ["operator"])
    owner_id = await create_user_with_roles("project-owner", [])
    delivery_user_id = await create_user_with_roles("project-delivery", [])

    owner_token = create_access_token(owner_id, [])
    created_project = await client.post(
        "/v1/projects",
        headers=auth(create_access_token(operator_id, ["operator"])),
        json=_project_payload(),
    )
    assert created_project.status_code == 201
    project_id = created_project.json()["id"]

    org = await create_org(client, owner_token, "org-project-auth")
    delivering_member_id = await add_member(str(org["id"]), delivery_user_id, "member")
    await _activate_contributor_capability(str(org["id"]))

    response = await client.post(
        f"/v1/orgs/{org['id']}/projects/{project_id}/proposals",
        json=_org_proposal_payload(delivering_member_id),
    )

    assert response.status_code == 401
