"""Unit tests for org library grant allocation and entitlement checks.

These tests lock the security-critical org License entitlement path before the
org library routes and download flow build on top of it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.frameworks.models import (
    Framework,
    FrameworkVersion,
    FrameworkVersionArtifact,
    License,
    LicenseGrant,
)
from app.modules.frameworks.models_artifact import Artifact
from app.modules.organizations import library_service
from app.modules.organizations.models import (
    Organization,
    OrgMember,
    OrgTeam,
    OrgTeamMember,
)
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for org-library unit tests."""
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
async def org_library_state(migrated_database: None) -> AsyncIterator[None]:
    """Reset org-library rows around each entitlement test."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        """Delete org-library rows before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(LicenseGrant))
            await session.execute(delete(License))
            await session.execute(delete(OrgTeamMember))
            await session.execute(delete(OrgTeam))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(FrameworkVersionArtifact))
            await session.execute(delete(FrameworkVersion))
            await session.execute(delete(Artifact))
            await session.execute(delete(Framework))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _create_user(prefix: str) -> User:
    """Create and return one verified user for org-library tests."""
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


async def _create_org(owner: User, *, slug: str) -> Organization:
    """Create and return one organization with an owner membership."""
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=slug,
                name="Operator Library Org",
                country="GB",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            await session.refresh(org)
            return org


async def _add_member(
    org_id: UUID,
    user_id: UUID,
    *,
    role: str = "member",
) -> OrgMember:
    """Create and return one organization member row."""
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=org_id, user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            await session.refresh(member)
            return member


async def _create_framework(contributor: User) -> Framework:
    """Create and return one contributor-owned Framework row."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor.id,
                contributor_org_id=None,
                title="Org Library Framework",
                description="A licensed framework.",
                category="framework",
                price=Decimal("199.00"),
                currency="USD",
                license_types=["team"],
            )
            session.add(framework)
            await session.flush()
            await session.refresh(framework)
            return framework


async def _create_framework_artifact_snapshot(
    framework: Framework,
    *,
    version: str = "1.0.0",
) -> Artifact:
    """Create and return one Artifact linked into the licensed version snapshot."""
    async with async_session_factory() as session:
        async with session.begin():
            artifact = Artifact(
                framework_id=framework.id,
                name="licensed.pdf",
                file_key=f"frameworks/{framework.id}/artifacts/licensed.pdf",
                file_size=2048,
                mime_type="application/pdf",
                scan_status="clean",
                processing_status="processed",
                current_for_framework=True,
            )
            session.add(artifact)
            await session.flush()
            snapshot = FrameworkVersion(
                framework_id=framework.id,
                version=version,
                change_type="major",
                change_log="Published for org library tests.",
            )
            session.add(snapshot)
            await session.flush()
            session.add(
                FrameworkVersionArtifact(
                    framework_version_id=snapshot.id,
                    artifact_id=artifact.id,
                    is_preview=False,
                )
            )
            await session.refresh(artifact)
            return artifact


async def _grant_org_license(framework_id: UUID, org_id: UUID) -> License:
    """Create and return one active org-owned License row."""
    async with async_session_factory() as session:
        async with session.begin():
            license_row = License(
                framework_id=framework_id,
                operator_id=None,
                licensee_org_id=org_id,
                license_type="team",
                status="active",
                version_at_grant="1.0.0",
                seats_used=1,
                seats_total=10,
            )
            session.add(license_row)
            await session.flush()
            await session.refresh(license_row)
            return license_row


async def _create_team(org_id: UUID, *, name: str) -> OrgTeam:
    """Create and return one organization team row."""
    async with async_session_factory() as session:
        async with session.begin():
            team = OrgTeam(org_id=org_id, name=name)
            session.add(team)
            await session.flush()
            await session.refresh(team)
            return team


@pytest.mark.asyncio
async def test_member_has_license_access_for_direct_member_grant(
    org_library_state: None,
) -> None:
    """A direct member grant satisfies org-library entitlement."""
    del org_library_state
    contributor = await _create_user("org-library-seller")
    owner = await _create_user("org-library-owner")
    member_user = await _create_user("org-library-member")
    org = await _create_org(owner, slug=f"org-library-{uuid4().hex[:6]}")
    member = await _add_member(org.id, member_user.id)
    framework = await _create_framework(contributor)
    license_row = await _grant_org_license(framework.id, org.id)

    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                LicenseGrant(
                    license_id=license_row.id,
                    member_id=member.id,
                    granted_by=member.id,
                )
            )

    async with async_session_factory() as session:
        has_access = await library_service.member_has_license_access(
            session,
            license_id=license_row.id,
            member_id=member.id,
        )

    assert has_access is True


@pytest.mark.asyncio
async def test_member_has_license_access_for_granted_team_membership(
    org_library_state: None,
) -> None:
    """A member inherits org-library access through a granted team."""
    del org_library_state
    contributor = await _create_user("org-library-seller")
    owner = await _create_user("org-library-owner")
    member_user = await _create_user("org-library-member")
    org = await _create_org(owner, slug=f"org-library-{uuid4().hex[:6]}")
    member = await _add_member(org.id, member_user.id)
    team = await _create_team(org.id, name=f"Team {uuid4().hex[:6]}")
    framework = await _create_framework(contributor)
    license_row = await _grant_org_license(framework.id, org.id)

    async with async_session_factory() as session:
        async with session.begin():
            session.add(OrgTeamMember(team_id=team.id, member_id=member.id))
            session.add(
                LicenseGrant(
                    license_id=license_row.id,
                    team_id=team.id,
                    granted_by=member.id,
                )
            )

    async with async_session_factory() as session:
        has_access = await library_service.member_has_license_access(
            session,
            license_id=license_row.id,
            member_id=member.id,
        )

    assert has_access is True


@pytest.mark.asyncio
async def test_member_has_license_access_returns_false_without_any_grant(
    org_library_state: None,
) -> None:
    """A member without a direct or team grant is not entitled to the License."""
    del org_library_state
    contributor = await _create_user("org-library-seller")
    owner = await _create_user("org-library-owner")
    member_user = await _create_user("org-library-member")
    org = await _create_org(owner, slug=f"org-library-{uuid4().hex[:6]}")
    member = await _add_member(org.id, member_user.id)
    framework = await _create_framework(contributor)
    license_row = await _grant_org_license(framework.id, org.id)

    async with async_session_factory() as session:
        has_access = await library_service.member_has_license_access(
            session,
            license_id=license_row.id,
            member_id=member.id,
        )

    assert has_access is False


@pytest.mark.asyncio
async def test_add_license_grant_rejects_member_outside_org(
    org_library_state: None,
) -> None:
    """Grant allocation rejects a member that does not belong to the license org."""
    del org_library_state
    contributor = await _create_user("org-library-seller")
    owner = await _create_user("org-library-owner")
    other_owner = await _create_user("org-library-other-owner")
    actor_user = await _create_user("org-library-actor")
    outside_user = await _create_user("org-library-outside")
    org = await _create_org(owner, slug=f"org-library-{uuid4().hex[:6]}")
    other_org = await _create_org(
        other_owner, slug=f"other-library-{uuid4().hex[:6]}"
    )
    actor_member = await _add_member(org.id, actor_user.id, role="admin")
    outside_member = await _add_member(other_org.id, outside_user.id)
    framework = await _create_framework(contributor)
    license_row = await _grant_org_license(framework.id, org.id)

    async with async_session_factory() as session:
        with pytest.raises(Exception) as exc_info:
            await library_service.add_license_grant(
                session,
                org_id=org.id,
                license_id=license_row.id,
                actor_member_id=actor_member.id,
                member_id=outside_member.id,
            )

    assert getattr(exc_info.value, "status_code", None) == 422


@pytest.mark.asyncio
async def test_add_license_grant_rejects_duplicate_member_grant(
    org_library_state: None,
) -> None:
    """Grant allocation returns 409 when the same member already has the License."""
    del org_library_state
    contributor = await _create_user("org-library-seller")
    owner = await _create_user("org-library-owner")
    actor_user = await _create_user("org-library-actor")
    member_user = await _create_user("org-library-member")
    org = await _create_org(owner, slug=f"org-library-{uuid4().hex[:6]}")
    actor_member = await _add_member(org.id, actor_user.id, role="admin")
    member = await _add_member(org.id, member_user.id)
    framework = await _create_framework(contributor)
    license_row = await _grant_org_license(framework.id, org.id)

    async with async_session_factory() as session:
        await library_service.add_license_grant(
            session,
            org_id=org.id,
            license_id=license_row.id,
            actor_member_id=actor_member.id,
            member_id=member.id,
        )

    async with async_session_factory() as session:
        with pytest.raises(Exception) as exc_info:
            await library_service.add_license_grant(
                session,
                org_id=org.id,
                license_id=license_row.id,
                actor_member_id=actor_member.id,
                member_id=member.id,
            )

    assert getattr(exc_info.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_request_org_artifact_download_rejects_ungranted_member(
    org_library_state: None,
) -> None:
    """Org Artifact download denies a member without any direct or team grant."""
    del org_library_state
    contributor = await _create_user("org-library-seller")
    owner = await _create_user("org-library-owner")
    member_user = await _create_user("org-library-member")
    org = await _create_org(owner, slug=f"org-library-{uuid4().hex[:6]}")
    member = await _add_member(org.id, member_user.id)
    framework = await _create_framework(contributor)
    artifact = await _create_framework_artifact_snapshot(framework)
    license_row = await _grant_org_license(framework.id, org.id)

    async with async_session_factory() as session:
        with pytest.raises(Exception) as exc_info:
            await library_service.request_org_artifact_download(
                session,
                org_id=org.id,
                license_id=license_row.id,
                artifact_id=artifact.id,
                member=member,
                ip_address="127.0.0.1",
            )

    assert getattr(exc_info.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_revoke_license_grant_removes_member_access(
    org_library_state: None,
) -> None:
    """Revoking an org License grant removes the member's entitlement."""
    del org_library_state
    contributor = await _create_user("org-library-seller")
    owner = await _create_user("org-library-owner")
    actor_user = await _create_user("org-library-actor")
    member_user = await _create_user("org-library-member")
    org = await _create_org(owner, slug=f"org-library-{uuid4().hex[:6]}")
    actor_member = await _add_member(org.id, actor_user.id, role="admin")
    member = await _add_member(org.id, member_user.id)
    framework = await _create_framework(contributor)
    license_row = await _grant_org_license(framework.id, org.id)

    async with async_session_factory() as session:
        grant = await library_service.add_license_grant(
            session,
            org_id=org.id,
            license_id=license_row.id,
            actor_member_id=actor_member.id,
            member_id=member.id,
        )

    async with async_session_factory() as session:
        await library_service.revoke_license_grant(
            session,
            org_id=org.id,
            license_id=license_row.id,
            grant_id=grant.id,
        )

    async with async_session_factory() as session:
        has_access = await library_service.member_has_license_access(
            session,
            license_id=license_row.id,
            member_id=member.id,
        )

    assert has_access is False


@pytest.mark.asyncio
async def test_request_org_artifact_download_rejects_artifact_outside_license_snapshot(
    org_library_state: None,
) -> None:
    """Org download returns 403 for an Artifact outside the licensed snapshot."""
    del org_library_state
    contributor = await _create_user("org-library-seller")
    owner = await _create_user("org-library-owner")
    member_user = await _create_user("org-library-member")
    org = await _create_org(owner, slug=f"org-library-{uuid4().hex[:6]}")
    member = await _add_member(org.id, member_user.id)
    framework = await _create_framework(contributor)
    _snapshot_artifact = await _create_framework_artifact_snapshot(framework)
    license_row = await _grant_org_license(framework.id, org.id)

    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                LicenseGrant(
                    license_id=license_row.id,
                    member_id=member.id,
                    granted_by=member.id,
                )
            )

    async with async_session_factory() as session:
        async with session.begin():
            current_artifact = Artifact(
                framework_id=framework.id,
                name="licensed-v2.pdf",
                file_key=f"frameworks/{framework.id}/artifacts/licensed-v2.pdf",
                file_size=4096,
                mime_type="application/pdf",
                scan_status="clean",
                processing_status="processed",
                current_for_framework=True,
            )
            session.add(current_artifact)
            await session.flush()

    async with async_session_factory() as session:
        with pytest.raises(Exception) as exc_info:
            await library_service.request_org_artifact_download(
                session,
                org_id=org.id,
                license_id=license_row.id,
                artifact_id=current_artifact.id,
                member=member,
                ip_address="127.0.0.1",
            )

    assert getattr(exc_info.value, "status_code", None) == 403
