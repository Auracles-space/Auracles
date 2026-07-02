"""DB-backed factor aggregator test for the attestor subject type.

Builds an attestor profile, stood attestations, ratings, and warnings inline,
then checks the rating average and reliability-penalty factors.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.attestation.models import (
    Attestation,
    AttestationRating,
    AttestorProfile,
    AttestorWarning,
)
from app.modules.auth.models import User, UserRole
from app.modules.reputation import factors
from app.modules.reputation.weights import load_config
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure reputation source tables exist before the test runs."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean(migrated_database: None) -> AsyncIterator[None]:
    """Reset attestor-factor rows in FK-safe order around each test."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(AttestationRating))
            await session.execute(delete(AttestorWarning))
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


async def _seed_attestor(*, ratings: list[int], warnings: int, late: int) -> UUID:
    """Create an attestor with stood attestations, ratings, and warnings."""
    async with async_session_factory() as session:
        async with session.begin():
            attestor = User(
                email=f"att-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Att",
                email_verified=True,
            )
            requestor = User(
                email=f"req-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Req",
                email_verified=True,
            )
            session.add_all([attestor, requestor])
            await session.flush()
            session.add(
                AttestorProfile(
                    user_id=attestor.id,
                    specializations=["ml"],
                    jurisdictions=["us"],
                    late_submission_count=late,
                )
            )
            for stars in ratings:
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
            for _ in range(warnings):
                session.add(
                    AttestorWarning(
                        attestor_id=attestor.id,
                        reason="upheld dispute",
                    )
                )
            return attestor.id


async def test_rating_factor_is_normalized_average(clean: None) -> None:
    """rating = (avg_stars - 1)/4 with evidence = number of ratings."""
    del clean
    attestor_id = await _seed_attestor(ratings=[5, 5, 4], warnings=0, late=0)

    async with async_session_factory() as session:
        cfg = await load_config(session, subject_type="attestor")
        result = await factors.attestor_factors(session, attestor_id, cfg)

    assert result["rating"].evidence == 3
    assert result["rating"].value == pytest.approx(
        Decimal("0.9167"),
        abs=Decimal("0.001"),
    )
    assert result["reliability"].value == Decimal("1")
    assert result["reliability"].evidence == 3


async def test_reliability_penalty_from_warnings_and_late(clean: None) -> None:
    """reliability = max(0, 1 - 0.10*(warnings + late_submission_count))."""
    del clean
    attestor_id = await _seed_attestor(ratings=[4, 4], warnings=2, late=1)

    async with async_session_factory() as session:
        cfg = await load_config(session, subject_type="attestor")
        result = await factors.attestor_factors(session, attestor_id, cfg)

    assert result["reliability"].value == Decimal("0.70")


async def test_no_ratings_scores_zero_without_error(clean: None) -> None:
    """An attestor with no ratings gets rating value 0 and evidence 0."""
    del clean
    attestor_id = await _seed_attestor(ratings=[], warnings=0, late=0)

    async with async_session_factory() as session:
        cfg = await load_config(session, subject_type="attestor")
        result = await factors.attestor_factors(session, attestor_id, cfg)

    assert result["rating"].value == Decimal("0")
    assert result["rating"].evidence == 0
