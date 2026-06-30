"""Unit tests for scored Attestor eligibility, screening, and ranking.

Verifies the hard gates (expired CoI, CoI subject conflict, at-cap) and the
deterministic score-then-FIFO ordering of ``_rank_eligible_attestors``.

Maps to: spec §2 (Eligibility + ranking).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import matching_service
from app.modules.attestation.models import (
    Attestation,
    AttestationOffer,
    AttestorProfile,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.modules.frameworks.models import Framework

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Remove ranking-test rows in FK-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(Attestation))
            await session.execute(delete(AttestorProfile))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(PlatformConfig))
            await session.execute(delete(Framework))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the test database is at alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database) -> AsyncIterator[None]:
    """Clean attestation state before and after each test."""
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
    """Provide an async session for ranking service calls."""
    del clean_state
    async with async_session_factory() as session:
        yield session


async def _make_user(role: str, prefix: str) -> User:
    """Create one user with an approved role row."""
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


async def _make_profile(
    user_id: UUID,
    *,
    specializations: list[str],
    jurisdictions: list[str],
    sectors: list[str] | None = None,
    framework_categories: list[str] | None = None,
    coi_declarations: list[dict[str, object]] | None = None,
    coi_valid: bool = True,
    approved_at: datetime | None = None,
) -> None:
    """Create one active attestor profile for ranking tests."""
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        session.add(
            AttestorProfile(
                user_id=user_id,
                specializations=specializations,
                jurisdictions=jurisdictions,
                sectors=sectors or [],
                framework_categories=framework_categories or [],
                coi_declarations=coi_declarations or [],
                coi_signed_at=now if coi_valid else now - timedelta(days=400),
                coi_expires_at=(
                    now + timedelta(days=365) if coi_valid else now - timedelta(days=1)
                ),
                approved_at=approved_at or now,
                active=True,
            )
        )
        await session.commit()


async def _make_attestation(
    requestor_id: UUID,
    *,
    target_id: UUID,
    target_type: str = "framework",
    specializations: list[str],
    jurisdictions: list[str],
    attestor_id: UUID | None = None,
    status_value: str = "matching",
) -> Attestation:
    """Create one attestation request for ranking tests."""
    async with async_session_factory() as session:
        attestation = Attestation(
            target_type=target_type,
            target_id=target_id,
            requestor_id=requestor_id,
            attestor_id=attestor_id,
            status=status_value,
            review_type="quality",
            fee_amount=Decimal("500.00"),
            currency="USD",
            requested_specializations=specializations,
            requested_jurisdictions=jurisdictions,
        )
        session.add(attestation)
        await session.commit()
        await session.refresh(attestation)
    return attestation


async def test_expired_coi_is_excluded(db_session) -> None:
    """Attestors with expired CoI declarations must not be ranked."""
    requestor = await _make_user("operator", "req")
    good = await _make_user("attestor", "good")
    expired = await _make_user("attestor", "expired")
    await _make_profile(good.id, specializations=["tax"], jurisdictions=["US"])
    await _make_profile(
        expired.id,
        specializations=["tax"],
        jurisdictions=["US"],
        coi_valid=False,
    )
    attestation = await _make_attestation(
        requestor.id,
        target_id=uuid4(),
        target_type="contributor",
        specializations=["tax"],
        jurisdictions=["US"],
    )

    ranked = await matching_service._rank_eligible_attestors(
        db_session,
        attestation=attestation,
        excluded_ids={requestor.id},
        limit=10,
        now=datetime.now(UTC),
    )

    ids = {candidate.user_id for candidate in ranked}
    assert good.id in ids
    assert expired.id not in ids


async def test_coi_subject_conflict_excluded(db_session) -> None:
    """A linked CoI declaration matching the target owner must exclude the attestor."""
    requestor = await _make_user("operator", "req")
    owner = await _make_user("contributor", "owner")
    conflicted = await _make_user("attestor", "conf")
    clean = await _make_user("attestor", "clean")

    async with async_session_factory() as session:
        framework = Framework(
            contributor_id=owner.id,
            title="Ranking Framework",
            description="Framework for ranking tests.",
            status="published",
            category="compliance",
            tags=["test"],
            price=Decimal("1.00"),
            license_types=["single_user"],
            published_at=datetime.now(UTC),
        )
        session.add(framework)
        await session.commit()
        await session.refresh(framework)

    await _make_profile(
        conflicted.id,
        specializations=["tax"],
        jurisdictions=["US"],
        coi_declarations=[
            {
                "entity": "Linked Owner",
                "entity_type": "firm",
                "relationship": "financial",
                "within_24mo": True,
                "subject_id": str(owner.id),
                "subject_kind": "user",
            }
        ],
    )
    await _make_profile(clean.id, specializations=["tax"], jurisdictions=["US"])
    attestation = await _make_attestation(
        requestor.id,
        target_id=framework.id,
        target_type="framework",
        specializations=["tax"],
        jurisdictions=["US"],
    )

    excluded_ids = await matching_service._excluded_attestor_ids(
        db_session,
        attestation,
    )
    ranked = await matching_service._rank_eligible_attestors(
        db_session,
        attestation=attestation,
        excluded_ids=excluded_ids,
        limit=10,
        now=datetime.now(UTC),
    )

    ids = {candidate.user_id for candidate in ranked}
    assert clean.id in ids
    assert conflicted.id not in ids


async def test_at_cap_attestor_excluded(db_session) -> None:
    """Attestors already at the active-assignment cap must be excluded."""
    requestor = await _make_user("operator", "req")
    busy = await _make_user("attestor", "busy")
    await _make_profile(busy.id, specializations=["tax"], jurisdictions=["US"])

    async with async_session_factory() as session:
        session.add(PlatformConfig(key="attestation_concurrency_cap", value="1"))
        await session.commit()

    await _make_attestation(
        requestor.id,
        target_id=uuid4(),
        target_type="contributor",
        specializations=["tax"],
        jurisdictions=["US"],
        attestor_id=busy.id,
        status_value="accepted",
    )
    attestation = await _make_attestation(
        requestor.id,
        target_id=uuid4(),
        target_type="contributor",
        specializations=["tax"],
        jurisdictions=["US"],
    )

    ranked = await matching_service._rank_eligible_attestors(
        db_session,
        attestation=attestation,
        excluded_ids={requestor.id},
        limit=10,
        now=datetime.now(UTC),
    )

    assert busy.id not in {candidate.user_id for candidate in ranked}


async def test_ranking_orders_by_score_then_fifo(db_session) -> None:
    """Higher scores rank first; ties fall back to approval time then user id."""
    requestor = await _make_user("operator", "req")
    owner = await _make_user("contributor", "owner")
    high = await _make_user("attestor", "high")
    low = await _make_user("attestor", "low")
    older = await _make_user("attestor", "older")
    base = datetime.now(UTC)

    async with async_session_factory() as session:
        framework = Framework(
            contributor_id=owner.id,
            title="Scored Ranking Framework",
            description="Framework for score-order tests.",
            status="published",
            category="compliance",
            tags=["test"],
            price=Decimal("1.00"),
            license_types=["single_user"],
            published_at=base,
        )
        session.add(framework)
        await session.commit()
        await session.refresh(framework)

    await _make_profile(
        high.id,
        specializations=["tax"],
        jurisdictions=["US"],
        framework_categories=["compliance"],
        approved_at=base,
    )
    await _make_profile(
        low.id,
        specializations=["tax"],
        jurisdictions=["US"],
        approved_at=base,
    )
    await _make_profile(
        older.id,
        specializations=["tax"],
        jurisdictions=["US"],
        approved_at=base - timedelta(days=1),
    )
    attestation = await _make_attestation(
        requestor.id,
        target_id=framework.id,
        target_type="framework",
        specializations=["tax"],
        jurisdictions=["US"],
    )

    ranked = await matching_service._rank_eligible_attestors(
        db_session,
        attestation=attestation,
        excluded_ids={requestor.id},
        limit=10,
        now=base,
    )

    order = [candidate.user_id for candidate in ranked]
    assert order[0] == high.id
    assert order.index(older.id) < order.index(low.id)
