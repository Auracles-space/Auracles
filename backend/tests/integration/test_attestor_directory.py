"""Integration tests for attestor directory reputation exposure."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.attestation import directory_service
from app.modules.attestation.models import AttestorProfile
from app.modules.auth.models import User, UserRole
from app.modules.reputation.models import ReputationScore
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure directory source tables exist before the test runs."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean(migrated_database: None) -> AsyncIterator[None]:
    """Reset directory rows in FK-safe order around each test."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(ReputationScore))
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


async def _seed_active_attestor() -> UUID:
    """Create one active attestor directory profile and return its user id."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"dir-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Directory Attestor",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(
                    user_id=user.id,
                    role="attestor",
                    approved_at=datetime.now(UTC),
                )
            )
            session.add(
                AttestorProfile(
                    user_id=user.id,
                    specializations=["ml"],
                    jurisdictions=["US"],
                    sectors=["PE"],
                    framework_categories=["Compliance"],
                    active=True,
                    coi_signed_at=datetime.now(UTC),
                    coi_expires_at=datetime.now(UTC).replace(
                        year=datetime.now(UTC).year + 1
                    ),
                )
            )
            return user.id


async def test_directory_entry_exposes_reputation_and_certified(clean: None) -> None:
    """A certified, scored attestor exposes a float reputation and certified=True."""
    del clean
    attestor_id = await _seed_active_attestor()

    async with async_session_factory() as session:
        async with session.begin():
            profile = await session.scalar(
                select(AttestorProfile).where(AttestorProfile.user_id == attestor_id)
            )
            assert profile is not None
            profile.certified_attestor_at = datetime.now(UTC)
            session.add(
                ReputationScore(
                    subject_type="attestor",
                    subject_id=attestor_id,
                    score=Decimal("88.00"),
                    components={},
                    is_provisional=False,
                )
            )

    async with async_session_factory() as session:
        entry = await directory_service.get_directory_profile(session, attestor_id)

    assert entry.certified is True
    assert entry.reputation == 88.0


async def test_directory_entry_hides_provisional_reputation(clean: None) -> None:
    """A provisional or unscored attestor exposes no score and no certification."""
    del clean
    attestor_id = await _seed_active_attestor()

    async with async_session_factory() as session:
        entry = await directory_service.get_directory_profile(session, attestor_id)

    assert entry.certified is False
    assert entry.reputation is None
