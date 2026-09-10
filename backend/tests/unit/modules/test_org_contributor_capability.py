"""Unit tests for org contributor capability activation and status changes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, func, select, update

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.organizations import contributor_service
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgContributorProfile,
    OrgMember,
)
from tests.conftest import verify_org_kyb
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for contributor capability tests."""
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
async def contributor_capability_state() -> AsyncIterator[None]:
    """Reset organization contributor rows around each capability test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete org-linked rows before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(OrgContributorProfile))
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
    """Create and return one verified user for contributor capability tests."""
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
                name="Contributor Capability Org",
                country="GB",
                created_by=owner.id,
            )
            session.add(organization)
            await session.flush()
            session.add_all(
                [
                    OrgMember(org_id=organization.id, user_id=owner.id, role="owner"),
                    # "admin" not "member": since 0779585f derived roles are scoped to
                    # owner/admin plus members of a team with the capability
                    # enabled. A plain member with no team correctly receives
                    # nothing, so these tests would assert the pre-0779585f rule.
                    OrgMember(org_id=organization.id, user_id=member.id, role="admin"),
                ]
            )
            await session.refresh(organization)
            org_id = organization.id

    # Capabilities are gated on business verification (DESIGN-1), so a fixture
    # org that activates one has to be verified first.
    await verify_org_kyb(org_id)
    async with async_session_factory() as session:
        refreshed = await session.get(Organization, org_id)
        assert refreshed is not None
        return refreshed


async def _contributor_roles(user_id: UUID) -> list[UserRole]:
    """Return all Contributor role rows for one user."""
    async with async_session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(UserRole).where(
                        UserRole.user_id == user_id,
                        UserRole.role == "contributor",
                    )
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_activate_creates_capability_profile_and_member_derived_role(
    migrated_database: None,
    contributor_capability_state: None,
) -> None:
    """Activation creates the capability/profile and grants member derived roles."""
    del migrated_database, contributor_capability_state
    owner = await _create_user("org-contributor-owner")
    member = await _create_user("org-contributor-member")
    organization = await _create_org_with_member(owner, member)

    async with async_session_factory() as session:
        capability = await contributor_service.activate_contributor_capability(
            session,
            org_id=organization.id,
            actor_id=owner.id,
        )

    assert capability.status == "active"
    async with async_session_factory() as session:
        profile = await session.scalar(
            select(OrgContributorProfile).where(
                OrgContributorProfile.org_id == organization.id
            )
        )
    assert profile is not None
    assert profile.active is True
    assert profile.verification_level == 1
    member_roles = await _contributor_roles(member.id)
    assert len(member_roles) == 1
    assert member_roles[0].source == "derived"


@pytest.mark.asyncio
async def test_activate_is_idempotent_and_does_not_duplicate_profile(
    migrated_database: None,
    contributor_capability_state: None,
) -> None:
    """Re-activating an active org leaves one profile row and active capability."""
    del migrated_database, contributor_capability_state
    owner = await _create_user("org-contributor-owner")
    member = await _create_user("org-contributor-member")
    organization = await _create_org_with_member(owner, member)

    async with async_session_factory() as session:
        await contributor_service.activate_contributor_capability(
            session,
            org_id=organization.id,
            actor_id=owner.id,
        )
    async with async_session_factory() as session:
        capability = await contributor_service.activate_contributor_capability(
            session,
            org_id=organization.id,
            actor_id=owner.id,
        )

    assert capability.status == "active"
    async with async_session_factory() as session:
        profile_count = await session.scalar(
            select(func.count())
            .select_from(OrgContributorProfile)
            .where(OrgContributorProfile.org_id == organization.id)
        )
    assert profile_count == 1


@pytest.mark.asyncio
async def test_activate_rejects_suspended_org(
    migrated_database: None,
    contributor_capability_state: None,
) -> None:
    """A suspended organization cannot self-activate the contributor capability."""
    del migrated_database, contributor_capability_state
    owner = await _create_user("org-contributor-owner")
    member = await _create_user("org-contributor-member")
    organization = await _create_org_with_member(owner, member)

    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Organization)
                .where(Organization.id == organization.id)
                .values(suspended_at=datetime.now(UTC))
            )

    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await contributor_service.activate_contributor_capability(
                session,
                org_id=organization.id,
                actor_id=owner.id,
            )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_status_changes_revoke_and_restore_derived_roles(
    migrated_database: None,
    contributor_capability_state: None,
) -> None:
    """Suspend revokes, reinstate re-grants, and revoke deactivates the profile."""
    del migrated_database, contributor_capability_state
    owner = await _create_user("org-contributor-owner")
    member = await _create_user("org-contributor-member")
    admin = await _create_user("platform-admin")
    organization = await _create_org_with_member(owner, member)

    async with async_session_factory() as session:
        await contributor_service.activate_contributor_capability(
            session,
            org_id=organization.id,
            actor_id=owner.id,
        )

    assert len(await _contributor_roles(member.id)) == 1

    async with async_session_factory() as session:
        await contributor_service.admin_set_contributor_capability_status(
            session,
            org_id=organization.id,
            admin_id=admin.id,
            status_value="suspended",
        )
    assert await _contributor_roles(member.id) == []

    async with async_session_factory() as session:
        await contributor_service.admin_set_contributor_capability_status(
            session,
            org_id=organization.id,
            admin_id=admin.id,
            status_value="active",
        )
    roles = await _contributor_roles(member.id)
    assert len(roles) == 1
    assert roles[0].source == "derived"

    async with async_session_factory() as session:
        await contributor_service.admin_set_contributor_capability_status(
            session,
            org_id=organization.id,
            admin_id=admin.id,
            status_value="revoked",
        )

    async with async_session_factory() as session:
        profile = await session.scalar(
            select(OrgContributorProfile).where(
                OrgContributorProfile.org_id == organization.id
            )
        )
        capability = await session.scalar(
            select(OrgCapability).where(
                OrgCapability.org_id == organization.id,
                OrgCapability.capability == "contributor",
            )
        )

    assert capability is not None
    assert capability.status == "revoked"
    assert profile is not None
    assert profile.active is False
