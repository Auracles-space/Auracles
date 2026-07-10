"""Unit tests for org-capable License ownership and grant allocation.

These tests lock the additive XOR ownership model for Licenses and the grant
allocation table before the shared-library and org-purchase tasks build on top
of them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, text
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.frameworks.license_ownership import resolve_license_holder
from app.modules.frameworks.models import Framework, License, LicenseGrant
from app.modules.organizations.models import Organization, OrgMember, OrgTeam
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for license ownership tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.downgrade(alembic_config, "2026_07_08_0072")
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        command.upgrade(alembic_config, "head")
        sync_engine.dispose()


@pytest.fixture
async def license_ownership_state(migrated_database: None) -> AsyncIterator[None]:
    """Reset Framework and identity rows around each license ownership test."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        """Delete License rows before shared identity cleanup."""
        async with async_session_factory() as session:
            grants_table_exists = bool(
                await session.scalar(
                    text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema = 'public' "
                        "AND table_name = 'license_grants'"
                    )
                )
            )
            if grants_table_exists:
                await session.execute(delete(LicenseGrant))
            await session.execute(delete(License))
            await session.execute(delete(Framework))
            await session.execute(delete(OrgTeam))
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


def _framework_kwargs() -> dict[str, object]:
    """Return minimal valid Framework fields for license ownership tests."""
    return {
        "title": "Org License Framework",
        "description": "A governance Framework.",
        "category": "framework",
        "price": Decimal("199.00"),
        "currency": "USD",
        "license_types": ["single_user"],
    }


async def _create_user(prefix: str) -> User:
    """Create and return one verified user for license ownership tests."""
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


async def _create_organization(owner: User, *, slug: str) -> Organization:
    """Create and return one organization with an owner membership."""
    async with async_session_factory() as session:
        async with session.begin():
            organization = Organization(
                slug=slug,
                name="License Holder Org",
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


async def _create_framework(contributor: User) -> Framework:
    """Create and return one contributor-owned Framework row."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor.id,
                contributor_org_id=None,
                **_framework_kwargs(),
            )
            session.add(framework)
            await session.flush()
            await session.refresh(framework)
            return framework


async def _add_member(
    org_id: UUID,
    user_id: UUID,
    *,
    role: str = "member",
) -> OrgMember:
    """Create and return one organization membership row."""
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=org_id, user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            await session.refresh(member)
            return member


async def _create_team(org_id: UUID, *, name: str) -> OrgTeam:
    """Create and return one organization team row."""
    async with async_session_factory() as session:
        async with session.begin():
            team = OrgTeam(org_id=org_id, name=name)
            session.add(team)
            await session.flush()
            await session.refresh(team)
            return team


def test_resolve_license_holder_returns_user_for_individual_license() -> None:
    """Holder resolution returns the user branch for individual Licenses."""
    operator_id = uuid4()
    framework_id = uuid4()
    license_row = License(
        framework_id=framework_id,
        operator_id=operator_id,
        license_type="single_user",
        version_at_grant="1.0.0",
    )

    holder = resolve_license_holder(license_row)

    assert holder.kind == "user"
    assert holder.user_id == operator_id
    assert holder.org_id is None


def test_resolve_license_holder_returns_org_for_org_license() -> None:
    """Holder resolution returns the org branch for organization Licenses."""
    framework_id = uuid4()
    org_id = uuid4()
    license_row = License(
        framework_id=framework_id,
        operator_id=None,
        licensee_org_id=org_id,
        license_type="team",
        version_at_grant="1.0.0",
    )

    holder = resolve_license_holder(license_row)

    assert holder.kind == "org"
    assert holder.org_id == org_id
    assert holder.user_id is None


@pytest.mark.asyncio
async def test_license_holder_xor_rejects_both_and_neither(
    migrated_database: None,
    license_ownership_state: None,
) -> None:
    """License persistence must reject both-holder and no-holder rows."""
    del migrated_database, license_ownership_state
    contributor = await _create_user("license-contributor")
    operator = await _create_user("license-operator")
    owner = await _create_user("license-org-owner")
    organization = await _create_organization(owner, slug="license-holder-org")
    framework = await _create_framework(contributor)

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    License(
                        framework_id=framework.id,
                        operator_id=operator.id,
                        licensee_org_id=organization.id,
                        license_type="organizational",
                        version_at_grant="1.0.0",
                    )
                )
                await session.flush()

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    License(
                        framework_id=framework.id,
                        operator_id=None,
                        licensee_org_id=None,
                        license_type="single_user",
                        version_at_grant="1.0.0",
                    )
                )
                await session.flush()


@pytest.mark.asyncio
async def test_license_grant_target_xor_rejects_both_and_neither(
    migrated_database: None,
    license_ownership_state: None,
) -> None:
    """LicenseGrant persistence must reject both-target and no-target rows."""
    del migrated_database, license_ownership_state
    contributor = await _create_user("grant-contributor")
    owner = await _create_user("grant-org-owner")
    member_user = await _create_user("grant-member")
    organization = await _create_organization(owner, slug="license-grant-org")
    member = await _add_member(organization.id, member_user.id)
    team = await _create_team(organization.id, name="Operations")
    framework = await _create_framework(contributor)

    async with async_session_factory() as session:
        async with session.begin():
            license_row = License(
                framework_id=framework.id,
                operator_id=None,
                licensee_org_id=organization.id,
                license_type="team",
                version_at_grant="1.0.0",
            )
            session.add(license_row)
            await session.flush()
            await session.refresh(license_row)

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    LicenseGrant(
                        license_id=license_row.id,
                        team_id=team.id,
                        member_id=member.id,
                        granted_by=member.id,
                    )
                )
                await session.flush()

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    LicenseGrant(
                        license_id=license_row.id,
                        team_id=None,
                        member_id=None,
                        granted_by=member.id,
                    )
                )
                await session.flush()


@pytest.mark.asyncio
async def test_license_grant_team_uniqueness_is_scoped_to_one_license(
    migrated_database: None,
    license_ownership_state: None,
) -> None:
    """One team cannot receive the same License twice, but can receive another."""
    del migrated_database, license_ownership_state
    contributor = await _create_user("grant-unique-contributor")
    owner = await _create_user("grant-unique-owner")
    member_user = await _create_user("grant-unique-member")
    organization = await _create_organization(owner, slug="license-grant-unique-org")
    member = await _add_member(organization.id, member_user.id)
    team = await _create_team(organization.id, name="Strategy")
    first_framework = await _create_framework(contributor)
    second_framework = await _create_framework(contributor)

    async with async_session_factory() as session:
        async with session.begin():
            first_license = License(
                framework_id=first_framework.id,
                operator_id=None,
                licensee_org_id=organization.id,
                license_type="team",
                version_at_grant="1.0.0",
            )
            second_license = License(
                framework_id=second_framework.id,
                operator_id=None,
                licensee_org_id=organization.id,
                license_type="team",
                version_at_grant="1.0.0",
            )
            session.add(first_license)
            session.add(second_license)
            await session.flush()
            await session.refresh(first_license)
            await session.refresh(second_license)

    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                LicenseGrant(
                    license_id=first_license.id,
                    team_id=team.id,
                    member_id=None,
                    granted_by=member.id,
                )
            )

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    LicenseGrant(
                        license_id=first_license.id,
                        team_id=team.id,
                        member_id=None,
                        granted_by=member.id,
                    )
                )
                await session.flush()

    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                LicenseGrant(
                    license_id=second_license.id,
                    team_id=team.id,
                    member_id=None,
                    granted_by=member.id,
                )
            )
