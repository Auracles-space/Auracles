"""Unit tests for team-capability enable/disable service methods."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.auth.models import UserRole
from app.modules.organizations import service as org_service
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgMember,
    OrgTeam,
    OrgTeamMember,
)
from tests.unit.modules.test_org_derived_roles import (  # noqa: F401
    _create_user,
    _org_admin_context,
    migrated_database,
    org_derived_role_state,
)

pytestmark = pytest.mark.asyncio


async def test_enable_requires_active_org_capability(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """Enabling a team capability requires the org capability to be active."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("guard-owner")
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Guard Org",
                slug="guard-org",
                country="US",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            team = OrgTeam(org_id=org.id, name="Sellers")
            session.add(team)
            await session.flush()
            org_id, team_id = org.id, team.id

    context = await _org_admin_context(org_id, owner.id)

    with pytest.raises(HTTPException) as exc:
        async with async_session_factory() as session:
            await org_service.enable_team_capability(
                db=session,
                context=context,
                team_id=team_id,
                capability="operator",
            )

    assert exc.value.status_code == 422


async def test_enable_then_disable_grants_and_revokes(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """Enabling grants the team member a role; disabling revokes it."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("flow-owner")
    member = await _create_user("flow-member")
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Flow Org",
                slug="flow-org",
                country="US",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            member_row = OrgMember(org_id=org.id, user_id=member.id, role="member")
            session.add(member_row)
            session.add(
                OrgCapability(org_id=org.id, capability="operator", status="active")
            )
            team = OrgTeam(org_id=org.id, name="Sellers")
            session.add(team)
            await session.flush()
            session.add(OrgTeamMember(team_id=team.id, member_id=member_row.id))
            org_id, team_id, member_user_id = org.id, team.id, member.id

    context = await _org_admin_context(org_id, owner.id)

    async with async_session_factory() as session:
        await org_service.enable_team_capability(
            db=session,
            context=context,
            team_id=team_id,
            capability="operator",
        )
    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member_user_id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        )
    assert role is not None

    async with async_session_factory() as session:
        await org_service.disable_team_capability(
            db=session,
            context=context,
            team_id=team_id,
            capability="operator",
        )
    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member_user_id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        )
    assert role is None
