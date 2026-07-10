"""Unit tests for org operator capability activation and status changes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, func, select, update

from app.core.database import Base, async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.organizations import contributor_service, operator_service
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for operator capability tests."""
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
async def operator_capability_state() -> AsyncIterator[None]:
    """Reset organization operator rows around each capability test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete org-linked rows before shared identity cleanup."""
        async with async_session_factory() as session:
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
    """Create and return one verified user for operator capability tests."""
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


async def _create_org_with_member(owner: User, member: User) -> Organization:
    """Create and return one organization with owner and plain member rows."""
    async with async_session_factory() as session:
        async with session.begin():
            organization = Organization(
                slug=f"org-{uuid4().hex[:6]}",
                name="Operator Capability Org",
                country="GB",
                created_by=owner.id,
            )
            session.add(organization)
            await session.flush()
            session.add_all(
                [
                    OrgMember(org_id=organization.id, user_id=owner.id, role="owner"),
                    OrgMember(org_id=organization.id, user_id=member.id, role="member"),
                ]
            )
            await session.refresh(organization)
            return organization


async def _operator_roles(user_id: UUID) -> list[UserRole]:
    """Return all Operator role rows for one user."""
    async with async_session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(UserRole).where(
                        UserRole.user_id == user_id,
                        UserRole.role == "operator",
                    )
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_activate_creates_capability_and_member_derived_operator_role(
    migrated_database: None,
    operator_capability_state: None,
) -> None:
    """Activation creates the capability row and grants member derived roles."""
    del migrated_database, operator_capability_state
    owner = await _create_user("org-operator-owner")
    member = await _create_user("org-operator-member")
    organization = await _create_org_with_member(owner, member)

    async with async_session_factory() as session:
        capability = await operator_service.activate_operator_capability(
            session,
            org_id=organization.id,
            actor_id=owner.id,
        )

    assert capability.status == "active"
    async with async_session_factory() as session:
        stored_capability = await session.scalar(
            select(OrgCapability).where(
                OrgCapability.org_id == organization.id,
                OrgCapability.capability == "operator",
            )
        )
    assert stored_capability is not None
    member_roles = await _operator_roles(member.id)
    assert len(member_roles) == 1
    assert member_roles[0].source == "derived"


@pytest.mark.asyncio
async def test_activate_is_idempotent_and_writes_no_operator_profile(
    migrated_database: None,
    operator_capability_state: None,
) -> None:
    """Re-activating an active org leaves one capability row and no profile table."""
    del migrated_database, operator_capability_state
    owner = await _create_user("org-operator-owner")
    member = await _create_user("org-operator-member")
    organization = await _create_org_with_member(owner, member)

    async with async_session_factory() as session:
        await operator_service.activate_operator_capability(
            session,
            org_id=organization.id,
            actor_id=owner.id,
        )
    async with async_session_factory() as session:
        capability = await operator_service.activate_operator_capability(
            session,
            org_id=organization.id,
            actor_id=owner.id,
        )

    assert capability.status == "active"
    assert "org_operator_profiles" not in Base.metadata.tables
    async with async_session_factory() as session:
        capability_count = await session.scalar(
            select(func.count())
            .select_from(OrgCapability)
            .where(
                OrgCapability.org_id == organization.id,
                OrgCapability.capability == "operator",
            )
        )
    assert capability_count == 1
    member_roles = await _operator_roles(member.id)
    assert len(member_roles) == 1
    assert member_roles[0].source == "derived"


@pytest.mark.asyncio
async def test_activate_rejects_suspended_org(
    migrated_database: None,
    operator_capability_state: None,
) -> None:
    """A suspended organization cannot self-activate the operator capability."""
    del migrated_database, operator_capability_state
    owner = await _create_user("org-operator-owner")
    member = await _create_user("org-operator-member")
    organization = await _create_org_with_member(owner, member)

    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Organization)
                .where(Organization.id == organization.id)
                .values(suspended_at=datetime.now(UTC))
            )

    async with async_session_factory() as session:
        with pytest.raises(Exception) as exc_info:
            await operator_service.activate_operator_capability(
                session,
                org_id=organization.id,
                actor_id=owner.id,
            )

    assert getattr(exc_info.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_admin_status_changes_only_operator_derived_roles(
    migrated_database: None,
    operator_capability_state: None,
) -> None:
    """Suspend/reinstate/revoke only touch derived Operator rows, not other roles."""
    del migrated_database, operator_capability_state
    owner = await _create_user("org-operator-owner")
    member = await _create_user("org-operator-member")
    admin = await _create_user("platform-admin")
    organization = await _create_org_with_member(owner, member)

    async with async_session_factory() as session:
        await contributor_service.activate_contributor_capability(
            session,
            org_id=organization.id,
            actor_id=owner.id,
        )
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=organization.id,
                    capability="attestor",
                    status="active",
                )
            )
    async with async_session_factory() as session:
        await operator_service.activate_operator_capability(
            session,
            org_id=organization.id,
            actor_id=owner.id,
        )
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                UserRole(
                    user_id=member.id,
                    role="operator",
                    source="self",
                    approved_at=datetime.now(UTC),
                )
            )
    async with async_session_factory() as session:
        from app.modules.organizations import service as org_service

        await org_service.sync_derived_roles(session, user_id=member.id)

    roles = await _operator_roles(member.id)
    assert {role.source for role in roles} == {"self", "derived"}

    async with async_session_factory() as session:
        await operator_service.admin_set_operator_capability_status(
            session,
            org_id=organization.id,
            admin_id=admin.id,
            status_value="suspended",
        )

    operator_roles = await _operator_roles(member.id)
    assert len(operator_roles) == 1
    assert operator_roles[0].source == "self"

    async with async_session_factory() as session:
        contributor_role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member.id,
                UserRole.role == "contributor",
                UserRole.source == "derived",
            )
        )
        attestor_role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member.id,
                UserRole.role == "attestor",
                UserRole.source == "derived",
            )
        )
    assert contributor_role is not None
    assert attestor_role is not None

    async with async_session_factory() as session:
        await operator_service.admin_set_operator_capability_status(
            session,
            org_id=organization.id,
            admin_id=admin.id,
            status_value="active",
        )

    operator_roles = await _operator_roles(member.id)
    assert len(operator_roles) == 2
    assert {role.source for role in operator_roles} == {"self", "derived"}

    async with async_session_factory() as session:
        await operator_service.admin_set_operator_capability_status(
            session,
            org_id=organization.id,
            admin_id=admin.id,
            status_value="revoked",
        )

    operator_roles = await _operator_roles(member.id)
    assert len(operator_roles) == 1
    assert operator_roles[0].source == "self"
