"""Unit tests for sticky Certified Attestor evaluation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.attestation.certification_service import (
    evaluate_attestor_certification,
)
from app.modules.attestation.models import (
    Attestation,
    AttestationRating,
    AttestorProfile,
)
from app.modules.auth.models import User, UserRole
from app.modules.reputation.weights import load_config
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure attestor certification source tables exist before the test runs."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean(migrated_database: None) -> AsyncIterator[None]:
    """Reset certification-related rows in FK-safe order around each test."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(AttestationRating))
            await session.execute(delete(Attestation))
            await session.execute(delete(AttestorProfile))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _seed(*, stood: int, stars: int) -> UUID:
    """Create an attestor with stood attestations each rated at one score."""
    async with async_session_factory() as session:
        async with session.begin():
            attestor = User(
                email=f"a-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="A",
                email_verified=True,
            )
            requestor = User(
                email=f"r-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="R",
                email_verified=True,
            )
            session.add_all([attestor, requestor])
            await session.flush()
            session.add(
                AttestorProfile(
                    user_id=attestor.id,
                    specializations=["ml"],
                    jurisdictions=["us"],
                )
            )
            for _ in range(stood):
                attestation = Attestation(
                    requestor_id=requestor.id,
                    attestor_id=attestor.id,
                    target_type="contributor",
                    target_id=requestor.id,
                    review_type="quality",
                    status="closed",
                    report_published_eligible=True,
                    fee_amount=Decimal("300.00"),
                    currency="USD",
                )
                session.add(attestation)
                await session.flush()
                session.add(
                    AttestationRating(
                        attestation_id=attestation.id,
                        rated_by=requestor.id,
                        stars=stars,
                    )
                )
            return attestor.id


async def _run(attestor_id: UUID) -> bool:
    """Evaluate certification for one attestor inside its own transaction."""
    async with async_session_factory() as session:
        async with session.begin():
            cfg = await load_config(session, subject_type="attestor")
            result = await evaluate_attestor_certification(
                session,
                attestor_id=attestor_id,
                cfg=cfg,
            )
    return result


async def _certified_at(attestor_id: UUID) -> datetime | None:
    """Return the profile certification timestamp for one attestor."""
    async with async_session_factory() as session:
        return await session.scalar(
            select(AttestorProfile.certified_attestor_at).where(
                AttestorProfile.user_id == attestor_id
            )
        )


async def test_certifies_when_thresholds_met(clean: None) -> None:
    """Ten stood attestations averaging at least 4.5 certifies the attestor."""
    del clean
    attestor_id = await _seed(stood=10, stars=5)

    assert await _run(attestor_id) is True
    assert await _certified_at(attestor_id) is not None

    async with async_session_factory() as session:
        audits = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "attestor_certified")
                )
            )
            .scalars()
            .all()
        )

    assert len(audits) == 1


async def test_below_count_threshold_does_not_certify(clean: None) -> None:
    """Nine stood attestations is below the default threshold of ten."""
    del clean
    attestor_id = await _seed(stood=9, stars=5)

    assert await _run(attestor_id) is False
    assert await _certified_at(attestor_id) is None


async def test_already_certified_is_sticky_and_not_reaudited(clean: None) -> None:
    """A certified attestor stays certified and is not re-stamped or re-audited."""
    del clean
    attestor_id = await _seed(stood=10, stars=5)

    assert await _run(attestor_id) is True
    first = await _certified_at(attestor_id)

    assert await _run(attestor_id) is False
    assert await _certified_at(attestor_id) == first

    async with async_session_factory() as session:
        audits = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.action == "attestor_certified")
                )
            )
            .scalars()
            .all()
        )

    assert len(audits) == 1
