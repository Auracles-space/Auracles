"""Unit tests for org member NDA signing and assignability.

Enforces the NDA-mechanics section of
docs/superpowers/specs/2026-07-04-org-attestor-design.md: signing is
required while the org attestor capability is pending or active, one
row per member is upserted on re-sign, and only a current-version
signature makes a member assignable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.organizations import nda_service
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgMember,
    OrgMemberNda,
)
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current database schema exists for NDA service tests."""
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
async def nda_state(migrated_database: None) -> AsyncIterator[None]:
    """Reset NDA, org, and identity rows around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete NDA and org rows before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(OrgMemberNda))
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


async def _create_org_member(
    *,
    attestor_status: str | None = None,
) -> tuple[UUID, UUID, UUID]:
    """Create user + org + owner member; return (org_id, user_id, member_id).

    Args:
        attestor_status: When set, an attestor capability row is created
            with this status.
    """
    suffix = uuid4().hex[:8]
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"nda-{suffix}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=f"nda-{suffix}",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            org = Organization(
                slug=f"nda-{suffix}",
                name="NDA Test Org",
                country="US",
                created_by=user.id,
            )
            session.add(org)
            await session.flush()
            member = OrgMember(org_id=org.id, user_id=user.id, role="owner")
            session.add(member)
            await session.flush()
            if attestor_status is not None:
                session.add(
                    OrgCapability(
                        org_id=org.id,
                        capability="attestor",
                        status=attestor_status,
                    )
                )
            return org.id, user.id, member.id


async def test_status_not_required_without_capability(nda_state: None) -> None:
    """No attestor capability row means the NDA is not required."""
    org_id, user_id, _ = await _create_org_member()
    async with async_session_factory() as session:
        status = await nda_service.get_nda_status(
            session, org_id=org_id, user_id=user_id
        )
    assert status.required is False
    assert status.signed_version is None
    assert status.signed_at is None
    assert status.current_version == app.state.settings.org_member_nda_version


@pytest.mark.parametrize("capability_status", ["pending", "active"])
async def test_status_required_for_pending_and_active(
    nda_state: None, capability_status: str
) -> None:
    """Pending and active attestor capabilities both require the NDA."""
    org_id, user_id, _ = await _create_org_member(attestor_status=capability_status)
    async with async_session_factory() as session:
        status = await nda_service.get_nda_status(
            session, org_id=org_id, user_id=user_id
        )
    assert status.required is True


async def test_sign_creates_row_and_reports_signed(nda_state: None) -> None:
    """Signing creates the member's NDA row at the current version."""
    org_id, user_id, member_id = await _create_org_member(attestor_status="pending")
    async with async_session_factory() as session:
        row = await nda_service.sign_nda(session, org_id=org_id, user_id=user_id)
        assert row.member_id == member_id
        assert row.nda_version == app.state.settings.org_member_nda_version
    async with async_session_factory() as session:
        status = await nda_service.get_nda_status(
            session, org_id=org_id, user_id=user_id
        )
    assert status.signed_version == app.state.settings.org_member_nda_version
    assert status.signed_at is not None


async def test_resign_after_version_bump_updates_row(
    nda_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-signing after a config version bump updates version and signed_at."""
    org_id, user_id, member_id = await _create_org_member(attestor_status="active")
    async with async_session_factory() as session:
        first = await nda_service.sign_nda(session, org_id=org_id, user_id=user_id)
        first_signed_at = first.signed_at

    monkeypatch.setattr(app.state.settings, "org_member_nda_version", "2.0")
    async with async_session_factory() as session:
        second = await nda_service.sign_nda(session, org_id=org_id, user_id=user_id)
        assert second.nda_version == "2.0"
        assert second.signed_at >= first_signed_at

    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(OrgMemberNda).where(OrgMemberNda.member_id == member_id)
            )
        ).all()
    assert len(rows) == 1


async def test_member_is_assignable_requires_current_version(
    nda_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Assignability is False unsigned or stale, True on the current version."""
    org_id, user_id, member_id = await _create_org_member(attestor_status="active")
    async with async_session_factory() as session:
        assert (
            await nda_service.member_is_assignable(session, member_id=member_id)
            is False
        )
        await nda_service.sign_nda(session, org_id=org_id, user_id=user_id)
        assert (
            await nda_service.member_is_assignable(session, member_id=member_id)
            is True
        )

    monkeypatch.setattr(app.state.settings, "org_member_nda_version", "2.0")
    async with async_session_factory() as session:
        assert (
            await nda_service.member_is_assignable(session, member_id=member_id)
            is False
        )
