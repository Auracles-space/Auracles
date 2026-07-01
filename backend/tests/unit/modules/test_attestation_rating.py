"""Unit tests for attestation rating capture (Module 5 section 5.3)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation.models import (
    Attestation,
    AttestationAnnotation,
    AttestationArtifactAccess,
    AttestationClarification,
    AttestationDispute,
    AttestationOffer,
    AttestationRating,
    AttestationRubricDimension,
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
    attestor = await _make_user("attestor", "attestor")
    requestor = await _make_user("operator", "requestor")
    attestation = Attestation(
        target_type="contributor",
        target_id=uuid4(),
        requestor_id=requestor.id,
        status="refunded",
        outcome="upheld_refund",
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
