"""Integration tests for the public attestor-organization directory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.attestation import directory_service
from app.modules.auth.models import User
from app.modules.organizations.models import (
    Organization,
    OrgAttestorProfile,
    OrgCapability,
    OrgMember,
)
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure directory source tables exist before the test runs."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean(migrated_database: None) -> AsyncIterator[None]:
    """Reset directory rows in FK-safe order around each test."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _seed_active_attestor_org() -> UUID:
    """Create one active attestor-org directory profile; return the org id."""
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            owner = User(
                email=f"dir-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Directory Owner",
                email_verified=True,
            )
            session.add(owner)
            await session.flush()
            org = Organization(
                slug=f"dir-org-{uuid4().hex[:6]}",
                name="Directory Attestor Org",
                country="US",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            session.add(
                OrgCapability(org_id=org.id, capability="attestor", status="active")
            )
            session.add(
                OrgAttestorProfile(
                    org_id=org.id,
                    specializations=["ml"],
                    jurisdictions=["united_states"],
                    sectors=["private_equity"],
                    functions=["compliance"],
                    active=True,
                    verification_level=2,
                    approved_at=now,
                    coi_signed_at=now,
                    coi_expires_at=now + timedelta(days=365),
                )
            )
            return org.id


async def test_directory_entry_exposes_org_identity_and_certified(
    clean: None,
) -> None:
    """A certified attestor org exposes org identity, counts, and certified=True."""
    del clean
    org_id = await _seed_active_attestor_org()

    async with async_session_factory() as session:
        async with session.begin():
            profile = await session.scalar(
                select(OrgAttestorProfile).where(OrgAttestorProfile.org_id == org_id)
            )
            assert profile is not None
            profile.certified_attestor_at = datetime.now(UTC)

    async with async_session_factory() as session:
        entry = await directory_service.get_directory_profile(session, org_id)

    assert entry.org_id == org_id
    assert entry.name == "Directory Attestor Org"
    assert entry.slug.startswith("dir-org-")
    assert entry.verification_level == 2
    assert entry.member_count == 1
    assert entry.completed_attestations == 0
    assert entry.certified is True
    # Org reputation scoring is wired in Task 10; None until then.
    assert entry.reputation is None


async def test_directory_entry_uncertified(clean: None) -> None:
    """An uncertified attestor org exposes certified=False and no reputation."""
    del clean
    org_id = await _seed_active_attestor_org()

    async with async_session_factory() as session:
        entry = await directory_service.get_directory_profile(session, org_id)

    assert entry.certified is False
    assert entry.reputation is None


async def test_list_directory_excludes_suspended_org(clean: None) -> None:
    """A suspended attestor org is hidden from the public directory listing."""
    del clean
    org_id = await _seed_active_attestor_org()

    async with async_session_factory() as session:
        listed = await directory_service.list_directory(
            db=session,
            sector=None,
            function=None,
            jurisdiction=None,
            level=None,
        )
    assert [e.org_id for e in listed] == [org_id]

    async with async_session_factory() as session:
        async with session.begin():
            org = await session.get(Organization, org_id)
            assert org is not None
            org.suspended_at = datetime.now(UTC)

    async with async_session_factory() as session:
        listed = await directory_service.list_directory(
            db=session,
            sector=None,
            function=None,
            jurisdiction=None,
            level=None,
        )
    assert listed == []


async def test_get_directory_profile_unknown_org_404(clean: None) -> None:
    """An unknown org id raises 404 from the directory profile lookup."""
    del clean
    from fastapi import HTTPException

    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await directory_service.get_directory_profile(session, uuid4())
    assert exc.value.status_code == 404


async def test_directory_endpoint_exposes_org_identity_no_member(
    client,
    clean: None,
) -> None:
    """The public endpoint lists org identity and leaks no member/internal data."""
    del clean
    org_id = await _seed_active_attestor_org()

    response = await client.get("/v1/attestor-orgs")

    assert response.status_code == 200, response.text
    entries = response.json()["attestors"]
    assert [entry["org_id"] for entry in entries] == [str(org_id)]
    entry = entries[0]
    assert entry["name"] == "Directory Attestor Org"
    assert entry["member_count"] == 1
    assert entry["verification_level"] == 2

    # No member identity, credentials, or internal governance fields leak.
    serialized = response.text.lower()
    assert "reviewing_member" not in serialized
    assert "user_id" not in serialized
    assert "email" not in serialized
    assert "coi" not in serialized
    assert "credential" not in serialized
