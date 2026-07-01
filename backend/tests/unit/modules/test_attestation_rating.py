"""Unit tests for attestation rating capture (Module 5 section 5.3)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import rating_service
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
async def db_session(clean_state) -> AsyncIterator:
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


async def _closed_after_accept(db_session) -> Attestation:
    attestor = await _make_user("attestor", "attestor")
    requestor = await _make_user("operator", "requestor")
    attestation = Attestation(
        target_type="contributor",
        target_id=uuid4(),
        requestor_id=requestor.id,
        attestor_id=attestor.id,
        status="closed",
        outcome="approved",
        report_published_eligible=True,
        fee_amount=Decimal("500.00"),
        currency="USD",
        requested_specializations=[],
        requested_jurisdictions=[],
    )
    db_session.add(attestation)
    await db_session.commit()
    await db_session.refresh(attestation)
    return attestation


async def _closed_conditional(db_session) -> Attestation:
    """Create a closed attestation whose determination was conditional."""
    attestor = await _make_user("attestor", "attestor")
    requestor = await _make_user("operator", "requestor")
    attestation = Attestation(
        target_type="contributor",
        target_id=uuid4(),
        requestor_id=requestor.id,
        attestor_id=attestor.id,
        status="closed",
        outcome="conditional",
        report_published_eligible=True,
        fee_amount=Decimal("500.00"),
        currency="USD",
        requested_specializations=[],
        requested_jurisdictions=[],
    )
    db_session.add(attestation)
    await db_session.commit()
    await db_session.refresh(attestation)
    return attestation


async def _closed_after_refund(db_session) -> Attestation:
    requestor = await _make_user("operator", "requestor")
    attestation = Attestation(
        target_type="contributor",
        target_id=uuid4(),
        requestor_id=requestor.id,
        status="refunded",
        outcome="rejected",
        fee_amount=Decimal("500.00"),
        currency="USD",
        requested_specializations=[],
        requested_jurisdictions=[],
    )
    db_session.add(attestation)
    await db_session.commit()
    await db_session.refresh(attestation)
    return attestation


async def test_rating_row_persists_and_is_unique(db_session) -> None:
    """One rating per attestation; a duplicate insert violates the unique key."""
    attestation = await _closed_after_accept(db_session)  # released via accept
    db_session.add(
        AttestationRating(
            attestation_id=attestation.id,
            rated_by=attestation.requestor_id,
            stars=5,
            comment="Thorough.",
        )
    )
    await db_session.commit()
    db_session.add(
        AttestationRating(
            attestation_id=attestation.id,
            rated_by=attestation.requestor_id,
            stars=4,
            comment=None,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_requestor_rates_closed_accepted_report(db_session) -> None:
    """A requestor can rate a report that stood via acceptance."""
    attestation = await _closed_after_accept(db_session)
    rating = await rating_service.submit_rating(
        db=db_session,
        requestor=await db_session.get(User, attestation.requestor_id),
        attestation_id=attestation.id,
        stars=5,
        comment="Clear and rigorous.",
    )
    assert rating.stars == 5


async def test_closed_conditional_report_is_rateable(db_session) -> None:
    """A stood report is rateable regardless of a non-approved determination.

    Enforces spec section 4.3 — eligibility keys off the report standing, not
    the attestor's approve/conditional/reject determination.
    """
    attestation = await _closed_conditional(db_session)
    rating = await rating_service.submit_rating(
        db=db_session,
        requestor=await db_session.get(User, attestation.requestor_id),
        attestation_id=attestation.id,
        stars=4,
        comment=None,
    )
    assert rating.stars == 4


async def test_duplicate_rating_conflicts(db_session) -> None:
    """A second rating on the same attestation is rejected 409."""
    attestation = await _closed_after_accept(db_session)
    requestor = await db_session.get(User, attestation.requestor_id)
    await rating_service.submit_rating(
        db=db_session, requestor=requestor,
        attestation_id=attestation.id, stars=4, comment=None,
    )
    # Each rating attempt is a fresh request with a freshly loaded user; the
    # service commits, expiring ORM instances, so reload before the retry.
    requestor = await db_session.get(User, attestation.requestor_id)
    with pytest.raises(HTTPException) as exc:
        await rating_service.submit_rating(
            db=db_session, requestor=requestor,
            attestation_id=attestation.id, stars=3, comment=None,
        )
    assert exc.value.status_code == 409


async def test_non_requestor_gets_404(db_session) -> None:
    """A non-requestor cannot rate; existence is hidden with 404."""
    attestation = await _closed_after_accept(db_session)
    stranger = await _make_user("operator", "stranger")
    with pytest.raises(HTTPException) as exc:
        await rating_service.submit_rating(
            db=db_session, requestor=stranger,
            attestation_id=attestation.id, stars=5, comment=None,
        )
    assert exc.value.status_code == 404


async def test_refunded_attestation_not_rateable(db_session) -> None:
    """A refunded (CoI-upheld) attestation's report did not stand — 409."""
    attestation = await _closed_after_refund(db_session)
    requestor = await db_session.get(User, attestation.requestor_id)
    with pytest.raises(HTTPException) as exc:
        await rating_service.submit_rating(
            db=db_session, requestor=requestor,
            attestation_id=attestation.id, stars=5, comment=None,
        )
    assert exc.value.status_code == 409
