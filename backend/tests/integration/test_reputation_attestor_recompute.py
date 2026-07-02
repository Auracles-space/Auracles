"""Integration: attestor reputation recompute and read path."""

from __future__ import annotations

import asyncio
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
)
from app.modules.auth.models import User, UserRole
from app.modules.reputation import service as reputation_service
from app.modules.reputation.models import ReputationScore
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import reputation as reputation_tasks

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
    """Reset reputation and attestation rows in FK-safe order around each test."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(ReputationScore))
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


async def _seed(*, stars: list[int]) -> UUID:
    """Create an attestor with stood attestations and requestor ratings."""
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
            for stars_value in stars:
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
                        stars=stars_value,
                    )
                )
            return attestor.id


async def test_recompute_subject_scores_attestor(clean: None) -> None:
    """recompute_subject stores a non-provisional attestor score with enough ratings."""
    del clean
    attestor_id = await _seed(stars=[5, 5, 5, 4])

    await reputation_tasks.recompute_subject(
        subject_type="attestor",
        subject_id=attestor_id,
    )

    async with async_session_factory() as session:
        score = await reputation_service.get_score(
            session,
            subject_type="attestor",
            subject_id=attestor_id,
        )

    assert score is not None
    assert score.is_provisional is False
    assert score.score is not None
    assert score.score > Decimal("75")


async def test_read_reputation_returns_attestor_payload(clean: None) -> None:
    """read_reputation returns an attestor payload and misses unknown ids."""
    del clean
    attestor_id = await _seed(stars=[5, 5, 5, 4])

    await reputation_tasks.recompute_subject(
        subject_type="attestor",
        subject_id=attestor_id,
    )

    async with async_session_factory() as session:
        payload = await reputation_service.read_reputation(
            session,
            subject_type="attestor",
            subject_id=attestor_id,
        )
        missing = await reputation_service.read_reputation(
            session,
            subject_type="attestor",
            subject_id=uuid4(),
        )

    assert payload is not None
    assert payload["subject_type"] == "attestor"
    assert missing is None


async def test_recompute_reputation_counts_active_attestors(clean: None) -> None:
    """The daily sweep includes active attestors in its returned counts."""
    del clean
    await _seed(stars=[5, 4, 5])

    await engine.dispose()
    result = await asyncio.to_thread(
        lambda: reputation_tasks.recompute_reputation.apply().get()
    )
    await engine.dispose()

    assert result["attestor"] == 1
