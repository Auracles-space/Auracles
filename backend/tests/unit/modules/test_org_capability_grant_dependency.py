"""Unit tests for organization capability-grant dependencies.

Enforces the team-scoped capability model on organization-scoped actions: a
caller holds a capability grant only as an owner/admin, or through membership
of a team with that capability enabled, while the organization capability is
active.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.organizations.dependencies import require_org_capability_grant
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgMember,
    OrgTeam,
    OrgTeamCapability,
    OrgTeamMember,
)
from tests.unit.modules import (
    test_org_derived_roles as derived_role_fixtures,  # noqa: F401
)

pytestmark = pytest.mark.asyncio

migrated_database = derived_role_fixtures.migrated_database
org_derived_role_state = derived_role_fixtures.org_derived_role_state


async def _run_dependency(*, org_id, user):
    """Invoke the contributor grant dependency with a real async session."""
    dependency = require_org_capability_grant("contributor")
    async with async_session_factory() as session:
        return await dependency(org_id=org_id, db=session, user=user)


async def _create_org_with_member(*, role: str):
    """Create an active contributor org and one member with the given role."""
    user = await derived_role_fixtures._create_user(f"grant-{role}")
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"grant-{uuid4().hex[:12]}",
                name="Grant Test Organization",
                country="GB",
                created_by=user.id,
            )
            session.add(org)
            await session.flush()
            member = OrgMember(org_id=org.id, user_id=user.id, role=role)
            session.add(member)
            session.add(
                OrgCapability(
                    org_id=org.id,
                    capability="contributor",
                    status="active",
                )
            )
            await session.flush()
            return org.id, user, member.id


async def test_owner_holds_grant(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """An owner holds an active contributor grant without team membership."""
    del migrated_database, org_derived_role_state
    org_id, user, _member_id = await _create_org_with_member(role="owner")

    context = await _run_dependency(org_id=org_id, user=user)

    assert context.org.id == org_id


async def test_admin_holds_grant(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """An admin holds an active contributor grant without team membership."""
    del migrated_database, org_derived_role_state
    org_id, user, _member_id = await _create_org_with_member(role="admin")

    context = await _run_dependency(org_id=org_id, user=user)

    assert context.member.role == "admin"


async def test_team_member_holds_grant(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """A plain member on a contributor-capability team holds the grant."""
    del migrated_database, org_derived_role_state
    org_id, user, member_id = await _create_org_with_member(role="member")
    async with async_session_factory() as session:
        async with session.begin():
            team = OrgTeam(org_id=org_id, name="Contributors")
            session.add(team)
            await session.flush()
            session.add(OrgTeamMember(team_id=team.id, member_id=member_id))
            session.add(OrgTeamCapability(team_id=team.id, capability="contributor"))

    context = await _run_dependency(org_id=org_id, user=user)

    assert context.member.id == member_id


async def test_plain_member_without_team_denied(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """A member outside contributor-capability teams is denied the grant."""
    del migrated_database, org_derived_role_state
    org_id, user, _member_id = await _create_org_with_member(role="member")

    with pytest.raises(HTTPException) as exc:
        await _run_dependency(org_id=org_id, user=user)

    assert exc.value.status_code == 403
    assert exc.value.detail["error_code"] == "capability_grant_required"


async def test_inactive_capability_denied(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """An owner is denied when the contributor capability is inactive."""
    del migrated_database, org_derived_role_state
    org_id, user, _member_id = await _create_org_with_member(role="owner")
    async with async_session_factory() as session:
        async with session.begin():
            capability = await session.scalar(
                select(OrgCapability).where(
                    OrgCapability.org_id == org_id,
                    OrgCapability.capability == "contributor",
                )
            )
            assert capability is not None
            capability.status = "suspended"

    with pytest.raises(HTTPException) as exc:
        await _run_dependency(org_id=org_id, user=user)

    assert exc.value.status_code == 403
    assert exc.value.detail["error_code"] == "capability_required"
