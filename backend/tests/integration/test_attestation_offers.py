"""Integration tests for scored Attestation offers.

Verifies that cohort offers persist AMM match scores and factor breakdowns when
the matching service dispatches the next eligible cohort.

Maps to: spec §5 (score persistence).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

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
from app.modules.organizations.models import (
    Organization,
    OrgAttestorProfile,
    OrgCapability,
    OrgMember,
)
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Remove offer-test rows in FK-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AuditLog))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(Attestation))
            await session.execute(delete(AttestorProfile))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(PlatformConfig))
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
    """Clean attestation state before and after the test."""
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
    """Provide an async session for service calls and assertions."""
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


async def _make_profile(user_id: UUID) -> None:
    """Create one eligible attestor profile for offer tests."""
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        session.add(
            AttestorProfile(
                user_id=user_id,
                specializations=["tax"],
                jurisdictions=["US"],
                sectors=["tax"],
                framework_categories=[],
                coi_declarations=[],
                coi_signed_at=now,
                coi_expires_at=now + timedelta(days=365),
                approved_at=now,
                active=True,
            )
        )
        await session.commit()


async def _make_attestation(requestor_id: UUID) -> Attestation:
    """Create one matching attestation ready for cohort dispatch."""
    async with async_session_factory() as session:
        attestation = Attestation(
            target_type="contributor",
            target_id=uuid4(),
            requestor_id=requestor_id,
            status="matching",
            review_type="quality",
            fee_amount=Decimal("500.00"),
            currency="USD",
            requested_specializations=["tax"],
            requested_jurisdictions=["US"],
        )
        session.add(attestation)
        await session.commit()
        await session.refresh(attestation)
    return attestation


async def test_all_screened_out_marks_needs_admin(db_session) -> None:
    """When every eligible Attestor is screened out, the request needs admin.

    Exercises the offer_next_cohort empty-candidate branch via the new
    availability gate: the only matching Attestor is already at the cap.
    """
    requestor = await _make_user("operator", "req")
    busy = await _make_user("attestor", "busy")
    await _make_profile(busy.id)

    async with async_session_factory() as session:
        async with session.begin():
            session.add(PlatformConfig(key="attestation_concurrency_cap", value="1"))
            session.add(
                Attestation(
                    target_type="contributor",
                    target_id=uuid4(),
                    requestor_id=requestor.id,
                    attestor_id=busy.id,
                    status="accepted",
                    review_type="quality",
                    fee_amount=Decimal("500.00"),
                    currency="USD",
                    requested_specializations=["tax"],
                    requested_jurisdictions=["US"],
                )
            )

    attestation = await _make_attestation(requestor.id)

    offers = await matching_service.offer_next_cohort(
        db_session,
        attestation_id=attestation.id,
    )

    assert offers == []
    refreshed = await db_session.get(Attestation, attestation.id)
    assert refreshed is not None
    assert refreshed.status == "needs_admin"


async def _make_org_attestor() -> UUID:
    """Create an active attestor org with an eligible profile; return org id."""
    owner_id = (await _make_user("operator", "orgowner")).id
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"org-{uuid4().hex[:6]}",
                name="Attestor Org",
                country="US",
                created_by=owner_id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner_id, role="owner"))
            session.add(
                OrgCapability(
                    org_id=org.id, capability="attestor", status="active"
                )
            )
            session.add(
                OrgAttestorProfile(
                    org_id=org.id,
                    specializations=["tax"],
                    jurisdictions=["US"],
                    sectors=["tax"],
                    framework_categories=[],
                    coi_declarations=[],
                    coi_signed_at=now,
                    coi_expires_at=now + timedelta(days=365),
                    approved_at=now,
                    active=True,
                )
            )
            return org.id


async def test_offer_persists_match_score(db_session) -> None:
    """offer_next_cohort stores match_score and score_breakdown on each offer."""
    requestor = await _make_user("operator", "req")
    await _make_org_attestor()
    attestation = await _make_attestation(requestor.id)

    offers = await matching_service.offer_next_cohort(
        db_session,
        attestation_id=attestation.id,
    )
    await db_session.flush()

    assert offers

    rows = await db_session.execute(
        select(AttestationOffer).where(
            AttestationOffer.attestation_id == attestation.id
        )
    )
    persisted_offers = rows.scalars().all()
    assert len(persisted_offers) == 1
    for offer in persisted_offers:
        assert offer.match_score is not None
        assert offer.score_breakdown is not None
        assert set(offer.score_breakdown) == {
            "sector",
            "category",
            "credential",
            "availability",
            "reputation",
        }
