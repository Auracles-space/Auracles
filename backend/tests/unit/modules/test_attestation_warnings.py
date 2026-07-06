"""Unit tests for attestor warnings and suspension review (Module 5 section 4.7).

Every upheld dispute records a formal attestor warning. A second warning inside
a rolling 12 months flags the attestor's profile for human suspension review —
never an automatic deactivation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import dispute_service
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestorWarning,
)
from app.modules.auth.models import User, UserRole
from app.modules.organizations.models import (
    Organization,
    OrgAttestorProfile,
    OrgMember,
)
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Clear test rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AuditLog))
            await session.execute(delete(AttestorWarning))
            await session.execute(delete(AttestationDispute))
            await session.execute(delete(Attestation))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the test database is upgraded to the latest alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database) -> AsyncIterator[None]:
    """Reset state before and after each test."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


@pytest.fixture
async def db_session(clean_state) -> AsyncIterator[AsyncSession]:
    """Provide an async session for tests."""
    del clean_state
    async with async_session_factory() as session:
        yield session


async def _make_attestor_org() -> tuple[UUID, UUID]:
    """Create an org with an active attestor profile; return (org_id, owner_id)."""
    async with async_session_factory() as session:
        async with session.begin():
            owner = User(
                email=f"owner-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="owner",
                email_verified=True,
            )
            session.add(owner)
            await session.flush()
            org = Organization(
                slug=f"warn-org-{uuid4().hex[:6]}",
                name="Warned Org",
                country="US",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            session.add(
                OrgAttestorProfile(
                    org_id=org.id,
                    specializations=["tax"],
                    jurisdictions=["US"],
                    sectors=[],
                    framework_categories=[],
                    active=True,
                    approved_at=datetime.now(UTC),
                )
            )
            return org.id, owner.id


async def _org_dispute_for(org_id: UUID) -> AttestationDispute:
    """Create a minimal disputed org attestation + dispute for the org."""
    async with async_session_factory() as session:
        async with session.begin():
            requestor = User(
                email=f"req-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="req",
                email_verified=True,
            )
            session.add(requestor)
            await session.flush()
            attestation = Attestation(
                target_type="contributor",
                target_id=uuid4(),
                requestor_id=requestor.id,
                attestor_org_id=org_id,
                status="disputed",
                fee_amount=Decimal("500.00"),
                currency="USD",
                requested_specializations=[],
                requested_jurisdictions=[],
            )
            session.add(attestation)
            await session.flush()
            dispute = AttestationDispute(
                attestation_id=attestation.id,
                raised_by=requestor.id,
                category="scope_error",
                reason="Placeholder dispute reason for org warning tests.",
                status="under_review",
            )
            session.add(dispute)
            await session.flush()
            dispute_id = dispute.id
    async with async_session_factory() as session:
        return await session.get(AttestationDispute, dispute_id)


async def test_org_warning_records_row_against_org(db_session) -> None:
    """An upheld org dispute records one warning keyed to the org, not a member."""
    org_id, owner_id = await _make_attestor_org()
    dispute = await _org_dispute_for(org_id)
    now = datetime.now(UTC)

    async with db_session.begin():
        recipients = await dispute_service._write_org_warning(
            db_session,
            org_id=org_id,
            dispute_id=dispute.id,
            reason="Dispute upheld (upheld_revise): revise scope.",
            now=now,
        )

    warning = await db_session.scalar(
        select(AttestorWarning).where(AttestorWarning.attestor_org_id == org_id)
    )
    profile = await db_session.scalar(
        select(OrgAttestorProfile).where(OrgAttestorProfile.org_id == org_id)
    )
    assert warning is not None
    assert warning.attestor_id is None
    assert profile is not None
    assert profile.suspension_review_at is None
    assert recipients == [owner_id]


async def test_org_second_warning_flags_suspension_review(db_session) -> None:
    """A second org warning within 12 months flags the org profile for review."""
    org_id, _owner_id = await _make_attestor_org()
    dispute_one = await _org_dispute_for(org_id)
    dispute_two = await _org_dispute_for(org_id)
    now = datetime.now(UTC)

    async with db_session.begin():
        await dispute_service._write_org_warning(
            db_session,
            org_id=org_id,
            dispute_id=dispute_one.id,
            reason="Dispute upheld (upheld_revise): first strike.",
            now=now,
        )
        await dispute_service._write_org_warning(
            db_session,
            org_id=org_id,
            dispute_id=dispute_two.id,
            reason="Dispute upheld (upheld_refund): second strike.",
            now=now,
        )

    profile = await db_session.scalar(
        select(OrgAttestorProfile).where(OrgAttestorProfile.org_id == org_id)
    )
    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "org_attestor_suspension_review_flagged",
        )
    )
    assert profile is not None
    assert profile.suspension_review_at is not None
    assert audit is not None
