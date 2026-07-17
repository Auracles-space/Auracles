"""Unit tests for organization-derived Contributor and Attestor roles.

These tests lock the dual-source Contributor role semantics needed for org
Contributor capability activation while preserving Attestor derived-role
behavior from the shipped org-attestor cut.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, func, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth import service as auth_service
from app.modules.auth.models import User, UserRole
from app.modules.organizations.dependencies import OrgContext
from app.modules.organizations import service as org_service
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgMember,
    OrgTeam,
    OrgTeamCapability,
    OrgTeamMember,
)
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for derived role tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        command.upgrade(alembic_config, "head")
        sync_engine.dispose()


@pytest.fixture
async def org_derived_role_state() -> AsyncIterator[None]:
    """Reset organization and role rows around each derived-role test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete org-linked rows before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(OrgTeamCapability))
            await session.execute(delete(OrgTeamMember))
            await session.execute(delete(OrgTeam))
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


async def _create_user(prefix: str) -> User:
    """Create and return one verified user for derived-role tests."""
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
            await session.refresh(user)
            return user


async def _seed_organization(owner: User, *, slug: str) -> Organization:
    """Create and return one organization with an owner membership."""
    async with async_session_factory() as session:
        async with session.begin():
            organization = Organization(
                slug=slug,
                name="Derived Role Org",
                country="GB",
                created_by=owner.id,
            )
            session.add(organization)
            await session.flush()
            session.add(
                OrgMember(org_id=organization.id, user_id=owner.id, role="owner")
            )
            await session.refresh(organization)
            return organization


async def _seed_capability(
    org_id: UUID,
    *,
    capability: str,
    status: str = "active",
) -> None:
    """Attach one organization capability row with the given status."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=org_id,
                    capability=capability,
                    status=status,
                )
            )


async def _org_admin_context(org_id: UUID, user_id: UUID) -> OrgContext:
    """Build an OrgContext for an owner/admin to call org services in tests."""
    async with async_session_factory() as session:
        org = await session.get(Organization, org_id)
        member = await session.scalar(
            select(OrgMember).where(
                OrgMember.org_id == org_id,
                OrgMember.user_id == user_id,
            )
        )
        user = await session.get(User, user_id)

    assert org is not None and member is not None and user is not None
    return OrgContext(org=org, member=member, user=user)


async def _role_rows(user_id: UUID, role: str) -> list[UserRole]:
    """Return all role rows for one user and role."""
    async with async_session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(UserRole)
                    .where(UserRole.user_id == user_id, UserRole.role == role)
                    .order_by(UserRole.created_at.asc())
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_sync_grants_contributor_role_for_active_org_member(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """An active contributor-capability org grants a derived Contributor role."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("contributor-derived-grant")
    organization = await _seed_organization(owner, slug="contributor-derived-grant")
    await _seed_capability(organization.id, capability="contributor")

    async with async_session_factory() as session:
        await org_service.sync_derived_roles(session, user_id=owner.id)

    roles = await _role_rows(owner.id, "contributor")
    assert len(roles) == 1
    assert roles[0].source == "derived"
    assert roles[0].approved_at is not None


@pytest.mark.asyncio
async def test_sync_removes_only_derived_contributor_role_when_self_role_exists(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """Leaving active contributor orgs removes only the derived Contributor row."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("contributor-derived-revoke")
    organization = await _seed_organization(owner, slug="contributor-derived-revoke")
    await _seed_capability(organization.id, capability="contributor")

    async with async_session_factory() as session:
        async with session.begin():
            session.add_all(
                [
                    UserRole(
                        user_id=owner.id,
                        role="contributor",
                        source="self",
                        approved_at=datetime.now(UTC),
                    ),
                    UserRole(
                        user_id=owner.id,
                        role="contributor",
                        source="derived",
                        approved_at=datetime.now(UTC),
                    ),
                ]
            )

    roles = await _role_rows(owner.id, "contributor")
    assert {role.source for role in roles} == {"self", "derived"}
    assert len(roles) == 2

    async with async_session_factory() as session:
        async with session.begin():
            membership = await session.scalar(
                select(OrgMember).where(
                    OrgMember.org_id == organization.id,
                    OrgMember.user_id == owner.id,
                )
            )
            assert membership is not None
            await session.delete(membership)

    roles = await _role_rows(owner.id, "contributor")
    assert {role.source for role in roles} == {"self", "derived"}
    assert len(roles) == 2

    async with async_session_factory() as session:
        await org_service.sync_derived_roles(session, user_id=owner.id)

    roles = await _role_rows(owner.id, "contributor")
    assert len(roles) == 1
    assert roles[0].source == "self"


@pytest.mark.asyncio
async def test_load_active_roles_accepts_contributor_from_either_source(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """Access-token role loading treats either Contributor source as sufficient."""
    del migrated_database, org_derived_role_state
    user = await _create_user("contributor-role-loading")

    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                UserRole(
                    user_id=user.id,
                    role="contributor",
                    source="self",
                    approved_at=datetime.now(UTC),
                )
            )
        roles = await auth_service._load_active_roles(session, user.id)

    assert roles == ["contributor"]

    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(UserRole).where(UserRole.user_id == user.id))
            session.add(
                UserRole(
                    user_id=user.id,
                    role="contributor",
                    source="derived",
                    approved_at=datetime.now(UTC),
                )
            )
        roles = await auth_service._load_active_roles(session, user.id)

    assert roles == ["contributor"]


@pytest.mark.asyncio
async def test_sync_grants_attestor_role_for_active_org_member(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """Attestor derived-role sync still works under the generalized map."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("attestor-derived-grant")
    organization = await _seed_organization(owner, slug="attestor-derived-grant")
    await _seed_capability(organization.id, capability="attestor")

    async with async_session_factory() as session:
        await org_service.sync_derived_roles(session, user_id=owner.id)

    roles = await _role_rows(owner.id, "attestor")
    assert len(roles) == 1
    assert roles[0].source == "derived"
    assert roles[0].approved_at is not None


@pytest.mark.asyncio
async def test_owner_holds_operator_role_without_team(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """An owner holds the derived Operator role without any team membership."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("owner-implicit")

    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Imp Org",
                slug=f"imp-org-{uuid4().hex[:8]}",
                country="US",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            session.add(
                OrgCapability(org_id=org.id, capability="operator", status="active")
            )

    async with async_session_factory() as session:
        await org_service.sync_derived_roles(session, user_id=owner.id)

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == owner.id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        )

    assert role is not None


@pytest.mark.asyncio
async def test_plain_member_without_team_has_no_operator_role(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """A plain member without an enabled team must not hold Operator."""
    del migrated_database, org_derived_role_state
    member = await _create_user("member-team-gated")

    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Gate Org",
                slug=f"gate-org-{uuid4().hex[:8]}",
                country="US",
                created_by=member.id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=member.id, role="member"))
            session.add(
                OrgCapability(org_id=org.id, capability="operator", status="active")
            )

    async with async_session_factory() as session:
        await org_service.sync_derived_roles(session, user_id=member.id)

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member.id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        )

    assert role is None


@pytest.mark.asyncio
async def test_admin_holds_operator_role_without_team(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """An admin holds the derived Operator role implicitly, without a team."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("owner-admin-implicit")
    admin = await _create_user("admin-implicit")

    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Adm Org",
                slug=f"adm-org-{uuid4().hex[:8]}",
                country="US",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            session.add(OrgMember(org_id=org.id, user_id=admin.id, role="admin"))
            session.add(
                OrgCapability(org_id=org.id, capability="operator", status="active")
            )

    async with async_session_factory() as session:
        await org_service.sync_derived_roles(session, user_id=admin.id)

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == admin.id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        )

    assert role is not None


@pytest.mark.asyncio
async def test_inactive_org_capability_revokes_operator_even_for_owner(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """A non-active Operator capability yields no derived role, even for owner."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("owner-capability-off")

    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Off Org",
                slug=f"off-org-{uuid4().hex[:8]}",
                country="US",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            session.add(
                OrgCapability(
                    org_id=org.id,
                    capability="operator",
                    status="suspended",
                )
            )

    async with async_session_factory() as session:
        await org_service.sync_derived_roles(session, user_id=owner.id)

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == owner.id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        )

    assert role is None


@pytest.mark.asyncio
async def test_sync_is_idempotent_for_contributor_derived_role(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """Repeated syncs leave exactly one derived Contributor row."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("contributor-derived-idempotent")
    organization = await _seed_organization(
        owner,
        slug="contributor-derived-idempotent",
    )
    await _seed_capability(organization.id, capability="contributor")

    async with async_session_factory() as session:
        await org_service.sync_derived_roles(session, user_id=owner.id)
    async with async_session_factory() as session:
        await org_service.sync_derived_roles(session, user_id=owner.id)

    async with async_session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(UserRole)
            .where(
                UserRole.user_id == owner.id,
                UserRole.role == "contributor",
                UserRole.source == "derived",
            )
        )

    assert count == 1


@pytest.mark.asyncio
async def test_adding_member_to_enabled_team_grants_operator_role(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """Adding a member to an enabled team grants the derived Operator role."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("team-owner")
    member = await _create_user("team-member")

    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Team Org",
                slug=f"team-org-{uuid4().hex[:8]}",
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
            session.add(OrgTeamCapability(team_id=team.id, capability="operator"))
            org_id, team_id, member_row_id = org.id, team.id, member_row.id

    context = await _org_admin_context(org_id, owner.id)
    async with async_session_factory() as session:
        await org_service.add_team_member(
            db=session,
            context=context,
            team_id=team_id,
            member_id=member_row_id,
        )

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member.id,
                UserRole.role == "operator",
                UserRole.source == "derived",
            )
        )

    assert role is not None


@pytest.mark.asyncio
async def test_removing_member_from_team_revokes_operator_role(
    migrated_database: None,
    org_derived_role_state: None,
) -> None:
    """Removing a member from the only enabled team revokes Operator."""
    del migrated_database, org_derived_role_state
    owner = await _create_user("team-owner-revoke")
    member = await _create_user("team-member-revoke")

    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                name="Rev Org",
                slug=f"rev-org-{uuid4().hex[:8]}",
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
            session.add(OrgTeamCapability(team_id=team.id, capability="operator"))
            session.add(OrgTeamMember(team_id=team.id, member_id=member_row.id))
            org_id, team_id, member_row_id, member_user_id = (
                org.id,
                team.id,
                member_row.id,
                member.id,
            )

    async with async_session_factory() as session:
        await org_service.sync_derived_roles(session, user_id=member_user_id)

    context = await _org_admin_context(org_id, owner.id)
    async with async_session_factory() as session:
        await org_service.remove_team_member(
            db=session,
            context=context,
            team_id=team_id,
            member_id=member_row_id,
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
