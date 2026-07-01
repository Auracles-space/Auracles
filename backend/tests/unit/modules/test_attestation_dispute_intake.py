"""Unit tests for attestation dispute intake hardening (Module 5 section 4.4)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import dispute_service
from app.modules.attestation.models import (
    Attestation,
    AttestationAnnotation,
    AttestationArtifactAccess,
    AttestationClarification,
    AttestationDispute,
    AttestationOffer,
    AttestationRating,
    AttestationRubricScore,
    AttestationUploadSession,
    AttestorProfile,
)
from app.modules.attestation.schemas import AttestationDisputeCreateRequest
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Clear test rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AuditLog))
            await session.execute(delete(AttestationRating))
            await session.execute(delete(AttestationClarification))
            await session.execute(delete(AttestationAnnotation))
            await session.execute(delete(AttestationRubricScore))
            await session.execute(delete(AttestationArtifactAccess))
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(AttestationDispute))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(Attestation))
            await session.execute(delete(AttestorProfile))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(PlatformConfig))
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


async def _make_user(role: str, prefix: str) -> User:
    """Create one verified user with one approved role row."""
    async with async_session_factory() as session:
        user = User(
            email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name=prefix,
            email_verified=True,
        )
        session.add(user)
        await session.flush()
        session.add(UserRole(user_id=user.id, role=role, approved_at=datetime.now(UTC)))
        await session.commit()
        await session.refresh(user)
    return user


async def _report_submitted_within_window(db_session) -> Attestation:
    attestor = await _make_user("attestor", "attestor")
    requestor = await _make_user("operator", "requestor")
    attestation = Attestation(
        target_type="contributor",
        target_id=uuid4(),
        requestor_id=requestor.id,
        attestor_id=attestor.id,
        status="report_submitted",
        outcome="approved",
        fee_amount=Decimal("500.00"),
        currency="USD",
        requested_specializations=[],
        requested_jurisdictions=[],
        dispute_window_ends_at=datetime.now(UTC) + timedelta(days=5),
    )
    db_session.add(attestation)
    await db_session.commit()
    await db_session.refresh(attestation)
    return attestation


async def test_dispute_requires_category(db_session) -> None:
    """A dispute row requires a category (DB not-null)."""
    attestation = await _report_submitted_within_window(db_session)
    requestor = await db_session.get(User, attestation.requestor_id)
    
    # Intentionally omitted category should raise DB IntegrityError
    db_session.add(
        AttestationDispute(
            attestation_id=attestation.id,
            raised_by=requestor.id,
            reason="I dispute this",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_dispute_below_min_evidence_length_is_422(db_session) -> None:
    """Evidence shorter than the configured minimum is rejected (vexatious guard)."""
    attestation = await _report_submitted_within_window(db_session)
    requestor = await db_session.get(User, attestation.requestor_id)
    with pytest.raises(HTTPException) as exc:
        await dispute_service.create_dispute(
            db=db_session, requestor=requestor, attestation_id=attestation.id,
            payload=AttestationDisputeCreateRequest(
                category="scope_error", reason="too short",
            ),
        )
    assert exc.value.status_code == 422


async def test_dispute_stores_category(db_session) -> None:
    """A valid dispute persists the chosen category."""
    attestation = await _report_submitted_within_window(db_session)
    requestor = await db_session.get(User, attestation.requestor_id)
    dispute = await dispute_service.create_dispute(
        db=db_session, requestor=requestor, attestation_id=attestation.id,
        payload=AttestationDisputeCreateRequest(
            category="material_inaccuracy",
            reason="Finding 3 misstates the 2025 revenue by a factor of ten, see p.4.",
        ),
    )
    assert dispute.category == "material_inaccuracy"


async def test_new_dispute_sets_standard_resolution_sla(db_session) -> None:
    """A newly raised dispute stamps a 5-business-day resolution due date."""
    from app.shared.business_days import add_business_days

    attestation = await _report_submitted_within_window(db_session)
    requestor = await db_session.get(User, attestation.requestor_id)
    dispute = await dispute_service.create_dispute(
        db=db_session,
        requestor=requestor,
        attestation_id=attestation.id,
        payload=AttestationDisputeCreateRequest(
            category="material_inaccuracy",
            reason="Finding 3 misstates the 2025 revenue by a factor of ten, p.4.",
        ),
    )
    assert dispute.resolution_due_at is not None
    # created_at (DB now()) and the service's current_time (Python now()) differ
    # by microseconds, so compare the business-day-shifted calendar dates.
    expected = add_business_days(
        dispute.created_at,
        dispute_service.RESOLUTION_SLA_STANDARD_BUSINESS_DAYS,
    )
    assert dispute.resolution_due_at.date() == expected.date()


async def _seed_rejected_disputes(
    db_session: AsyncSession, *, requestor_id: UUID, count: int, resolved_at: datetime
) -> None:
    for _ in range(count):
        attestation = await _report_submitted_within_window(db_session)
        attestation.requestor_id = requestor_id
        await db_session.flush()
        db_session.add(
            AttestationDispute(
                attestation_id=attestation.id,
                raised_by=requestor_id,
                category="material_inaccuracy",
                reason="Test reason",
                status="resolved",
                outcome="rejected",
                resolved_at=resolved_at,
            )
        )
    await db_session.commit()


async def test_requestor_flag_threshold(db_session) -> None:
    """Three rejected disputes inside 12 months flags the requestor."""
    frozen_now = datetime.now(UTC)
    requestor = await _make_user("operator", "serial")
    await _seed_rejected_disputes(db_session, requestor_id=requestor.id, count=2,
                                  resolved_at=frozen_now)

    count_2 = await dispute_service.requestor_rejected_dispute_count(
        db_session, requestor_id=requestor.id, now=frozen_now
    )
    assert count_2 < dispute_service.REQUESTOR_FLAG_THRESHOLD

    await _seed_rejected_disputes(db_session, requestor_id=requestor.id, count=1,
                                  resolved_at=frozen_now)
    count_3 = await dispute_service.requestor_rejected_dispute_count(
        db_session, requestor_id=requestor.id, now=frozen_now
    )
    assert count_3 >= dispute_service.REQUESTOR_FLAG_THRESHOLD


async def test_requestor_flag_ignores_disputes_older_than_window(
    db_session,
) -> None:
    """Disputes resolved more than 12 months ago fall outside the count.

    Enforces spec section 4.5 — the abuse signal is a trailing-12-month
    rolling window, not a lifetime tally.
    """
    frozen_now = datetime.now(UTC)
    aged = frozen_now - timedelta(days=dispute_service.REQUESTOR_FLAG_WINDOW_DAYS + 1)
    requestor = await _make_user("operator", "reformed")
    await _seed_rejected_disputes(
        db_session, requestor_id=requestor.id, count=3, resolved_at=aged
    )

    count = await dispute_service.requestor_rejected_dispute_count(
        db_session, requestor_id=requestor.id, now=frozen_now
    )
    assert count == 0
