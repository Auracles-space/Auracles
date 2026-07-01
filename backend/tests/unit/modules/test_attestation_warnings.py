"""Unit tests for attestor warnings and suspension review (Module 5 section 4.7).

Every upheld dispute records a formal attestor warning. A second warning inside
a rolling 12 months flags the attestor's profile for human suspension review —
never an automatic deactivation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import dispute_service
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestorProfile,
    AttestorWarning,
)
from app.modules.auth.models import User, UserRole
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
            await session.execute(delete(AttestorProfile))
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


async def _make_attestor_with_profile() -> User:
    """Create an approved attestor with a matching profile row."""
    async with async_session_factory() as session:
        user = User(
            email=f"attestor-{uuid4().hex[:8]}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="attestor",
            email_verified=True,
        )
        session.add(user)
        await session.flush()
        session.add(
            UserRole(user_id=user.id, role="attestor", approved_at=datetime.now(UTC))
        )
        session.add(
            AttestorProfile(
                user_id=user.id,
                specializations=["tax"],
                jurisdictions=["US"],
                sectors=[],
                framework_categories=[],
                active=True,
                approved_at=datetime.now(UTC),
                coi_declarations=[],
            )
        )
        await session.commit()
        await session.refresh(user)
    return user


async def _dispute_for(attestor_id: UUID) -> AttestationDispute:
    """Create a minimal disputed attestation + dispute for the attestor."""
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
                attestor_id=attestor_id,
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
                reason="Placeholder dispute reason for warning tests.",
                status="under_review",
            )
            session.add(dispute)
            await session.flush()
            dispute_id = dispute.id
    async with async_session_factory() as session:
        return await session.get(AttestationDispute, dispute_id)


async def test_write_warning_records_row(db_session) -> None:
    """A single upheld dispute records one warning and does not flag review."""
    attestor = await _make_attestor_with_profile()
    dispute = await _dispute_for(attestor.id)
    now = datetime.now(UTC)

    async with db_session.begin():
        await dispute_service._write_warning(
            db_session,
            attestor_id=attestor.id,
            dispute_id=dispute.id,
            reason="Dispute upheld (upheld_revise): revise scope.",
            now=now,
        )

    count = await db_session.scalar(
        select(func.count())
        .select_from(AttestorWarning)
        .where(AttestorWarning.attestor_id == attestor.id)
    )
    profile = await db_session.scalar(
        select(AttestorProfile).where(AttestorProfile.user_id == attestor.id)
    )
    assert count == 1
    assert profile is not None
    assert profile.suspension_review_at is None


async def test_second_warning_flags_suspension_review(db_session) -> None:
    """A second warning within 12 months flips the suspension-review flag."""
    attestor = await _make_attestor_with_profile()
    dispute_one = await _dispute_for(attestor.id)
    dispute_two = await _dispute_for(attestor.id)
    now = datetime.now(UTC)

    async with db_session.begin():
        await dispute_service._write_warning(
            db_session,
            attestor_id=attestor.id,
            dispute_id=dispute_one.id,
            reason="Dispute upheld (upheld_revise): first strike.",
            now=now,
        )
        await dispute_service._write_warning(
            db_session,
            attestor_id=attestor.id,
            dispute_id=dispute_two.id,
            reason="Dispute upheld (upheld_refund): second strike.",
            now=now,
        )

    profile = await db_session.scalar(
        select(AttestorProfile).where(AttestorProfile.user_id == attestor.id)
    )
    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "attestor_suspension_review_flagged",
        )
    )
    assert profile is not None
    assert profile.suspension_review_at is not None
    assert audit is not None


async def test_warning_outside_window_not_counted(db_session) -> None:
    """A warning older than 12 months does not contribute to the review count."""
    attestor = await _make_attestor_with_profile()
    dispute_old = await _dispute_for(attestor.id)
    dispute_new = await _dispute_for(attestor.id)
    now = datetime.now(UTC)

    async with db_session.begin():
        aged_days = dispute_service.SUSPENSION_REVIEW_WINDOW_DAYS + 1
        aged = AttestorWarning(
            attestor_id=attestor.id,
            dispute_id=dispute_old.id,
            reason="Stale warning outside the window.",
            created_at=now - timedelta(days=aged_days),
        )
        db_session.add(aged)
        await db_session.flush()
        await dispute_service._write_warning(
            db_session,
            attestor_id=attestor.id,
            dispute_id=dispute_new.id,
            reason="Dispute upheld (upheld_revise): only recent strike.",
            now=now,
        )

    profile = await db_session.scalar(
        select(AttestorProfile).where(AttestorProfile.user_id == attestor.id)
    )
    assert profile is not None
    assert profile.suspension_review_at is None
