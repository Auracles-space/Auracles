"""Org attestor model persistence tests.

Enforces the spec data-model section (org_attestor_applications,
org_attestor_profiles, org_member_ndas) from
docs/superpowers/specs/2026-07-04-org-attestor-design.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgAttestorProfile,
    OrgMember,
    OrgMemberNda,
)
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current database schema exists for model tests."""
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
async def org_attestor_state(migrated_database: None) -> AsyncIterator[None]:
    """Reset org-attestor and identity rows around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete org-attestor rows before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(OrgMemberNda))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgAttestorApplication))
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


async def _create_org_with_member() -> tuple[Organization, OrgMember]:
    """Create a user, an organization, and its owner membership row."""
    suffix = uuid4().hex[:8]
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"org-attestor-{suffix}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=f"org-attestor-{suffix}",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            org = Organization(
                slug=f"acme-{suffix}",
                name="Acme Audit Ltd",
                country="US",
                created_by=user.id,
            )
            session.add(org)
            await session.flush()
            member = OrgMember(org_id=org.id, user_id=user.id, role="owner")
            session.add(member)
            await session.flush()
            await session.refresh(org)
            await session.refresh(member)
    return org, member


async def test_org_attestor_application_round_trip(
    org_attestor_state: None,
) -> None:
    """Application persists all gate fields; status defaults to draft."""
    org, _ = await _create_org_with_member()
    async with async_session_factory() as session:
        async with session.begin():
            row = OrgAttestorApplication(
                org_id=org.id,
                legal_name="Acme Audit Ltd",
                specializations=["security"],
                jurisdictions=["US"],
                credentials_summary="ISO auditors",
                sample_work={"links": []},
                professional_references="refs",
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            assert row.status == "draft"
            assert row.kyb_verified_at is None
            assert row.trial_member_id is None
            assert row.coi_declarations == []
            assert row.sectors == []
            assert row.functions == []
            assert row.incorporation_doc_keys == []


async def test_one_live_application_per_org(org_attestor_state: None) -> None:
    """Partial unique index rejects a second live application for one org."""
    org, _ = await _create_org_with_member()

    def _application() -> OrgAttestorApplication:
        """Build a minimal draft application row for the shared org."""
        return OrgAttestorApplication(
            org_id=org.id,
            legal_name="Acme Audit Ltd",
            specializations=["security"],
            jurisdictions=["US"],
            credentials_summary="ISO auditors",
            sample_work={"links": []},
            professional_references="refs",
        )

    async with async_session_factory() as session:
        async with session.begin():
            session.add(_application())
    async with async_session_factory() as session:
        session.add(_application())
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_rejected_application_frees_live_slot(
    org_attestor_state: None,
) -> None:
    """A rejected application does not block creating a new draft."""
    org, _ = await _create_org_with_member()
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgAttestorApplication(
                    org_id=org.id,
                    status="rejected",
                    legal_name="Acme Audit Ltd",
                    specializations=["security"],
                    jurisdictions=["US"],
                    credentials_summary="ISO auditors",
                    sample_work={"links": []},
                    professional_references="refs",
                )
            )
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgAttestorApplication(
                    org_id=org.id,
                    legal_name="Acme Audit Ltd",
                    specializations=["security"],
                    jurisdictions=["US"],
                    credentials_summary="ISO auditors",
                    sample_work={"links": []},
                    professional_references="refs",
                )
            )


async def test_org_attestor_profile_round_trip_and_unique_org(
    org_attestor_state: None,
) -> None:
    """Profile persists matching fields with defaults; one profile per org."""
    org, _ = await _create_org_with_member()
    async with async_session_factory() as session:
        async with session.begin():
            profile = OrgAttestorProfile(
                org_id=org.id,
                specializations=["security"],
                jurisdictions=["US"],
            )
            session.add(profile)
            await session.flush()
            await session.refresh(profile)
            assert profile.active is True
            assert profile.verification_level == 1
            assert profile.late_submission_count == 0
            assert profile.certified_attestor_at is None
    async with async_session_factory() as session:
        session.add(
            OrgAttestorProfile(
                org_id=org.id,
                specializations=["privacy"],
                jurisdictions=["GB"],
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_org_member_nda_unique_per_member(org_attestor_state: None) -> None:
    """One NDA signature row per member (re-sign updates version, Task 3)."""
    _, member = await _create_org_with_member()
    async with async_session_factory() as session:
        async with session.begin():
            session.add(OrgMemberNda(member_id=member.id, nda_version="1.0"))
    async with async_session_factory() as session:
        session.add(OrgMemberNda(member_id=member.id, nda_version="1.1"))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
