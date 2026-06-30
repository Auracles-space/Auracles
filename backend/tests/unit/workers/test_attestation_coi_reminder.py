"""Unit tests for the CoI re-sign reminder service.

Verifies that expiring Attestor CoI declarations trigger one reminder and set
the cycle-dedup timestamp used by the daily Beat task.

Maps to: spec §6 (CoI re-sign reminder Beat task).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import matching_service
from app.modules.attestation.models import AttestorProfile
from app.modules.auth.models import User, UserRole

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Remove reminder-test rows in FK-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestorProfile))
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
    """Clean attestor reminder state before and after each test."""
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
    """Provide an async session for reminder service calls."""
    del clean_state
    async with async_session_factory() as session:
        yield session


async def _attestor_with_expiry(expires_at: datetime, signed_at: datetime) -> UUID:
    """Create one active Attestor with a specific CoI expiry cycle."""
    async with async_session_factory() as session:
        user = User(
            email=f"att-{uuid4().hex[:8]}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="att",
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
                specializations=["tax"],
                jurisdictions=["US"],
                active=True,
                coi_signed_at=signed_at,
                coi_expires_at=expires_at,
            )
        )
        await session.commit()
    return user.id


@pytest.fixture(autouse=True)
def _stub_notifications(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, UUID]]:
    """Capture reminder notifications instead of dispatching real fanout."""
    sent: list[tuple[str, UUID]] = []
    monkeypatch.setattr(
        matching_service.attestation_notifications,
        "notify_coi_expiring",
        lambda user_id, *, expires_at: sent.append(("expiring", user_id)),
    )
    monkeypatch.setattr(
        matching_service.attestation_notifications,
        "notify_coi_lapsed",
        lambda user_id, *, expires_at: sent.append(("lapsed", user_id)),
    )
    return sent


async def test_reminder_within_30_days(db_session, _stub_notifications) -> None:
    """An active attestor inside the 30-day window gets one expiring reminder."""
    now = datetime.now(UTC)
    user_id = await _attestor_with_expiry(
        now + timedelta(days=10),
        now - timedelta(days=355),
    )

    count = await matching_service.send_coi_resign_reminders(db_session, now=now)

    assert count == 1
    assert ("expiring", user_id) in _stub_notifications
    reminder_sent_at = await db_session.scalar(
        select(AttestorProfile.coi_reminder_sent_at).where(
            AttestorProfile.user_id == user_id
        )
    )
    assert reminder_sent_at is not None


async def test_reminder_lapsed(db_session, _stub_notifications) -> None:
    """An expired CoI declaration gets the lapsed reminder variant."""
    now = datetime.now(UTC)
    user_id = await _attestor_with_expiry(
        now - timedelta(days=2),
        now - timedelta(days=367),
    )

    count = await matching_service.send_coi_resign_reminders(db_session, now=now)

    assert count == 1
    assert ("lapsed", user_id) in _stub_notifications


async def test_reminder_idempotent_same_cycle(db_session, _stub_notifications) -> None:
    """Re-running the sweep in the same cycle must not re-notify the same attestor."""
    now = datetime.now(UTC)
    await _attestor_with_expiry(
        now + timedelta(days=10),
        now - timedelta(days=355),
    )

    first = await matching_service.send_coi_resign_reminders(db_session, now=now)
    second = await matching_service.send_coi_resign_reminders(
        db_session,
        now=now + timedelta(hours=1),
    )

    assert first == 1
    assert second == 0


async def test_no_reminder_when_far_from_expiry(
    db_session,
    _stub_notifications,
) -> None:
    """Attestors outside the 30-day lead window must not be notified."""
    now = datetime.now(UTC)
    await _attestor_with_expiry(
        now + timedelta(days=200),
        now - timedelta(days=165),
    )

    count = await matching_service.send_coi_resign_reminders(db_session, now=now)

    assert count == 0
    assert _stub_notifications == []
