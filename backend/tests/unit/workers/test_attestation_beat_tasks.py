"""Scheduled Attestation beat task tests.

Covers the Celery wrappers in ``app/workers/tasks/attestation_beat.py`` and
their thin async helpers end-to-end. The wrappers run their work inside the
worker's own event loop via ``run_async``; the tests cross event loops with
``asyncio.to_thread`` and dispose the shared async engine around each crossing
so pooled asyncpg connections are never reused by a different loop.

The five maintenance tasks each select stale/overdue rows. Against an empty
Attestation table they perform a clean no-op pass, which exercises every line
of the beat module and proves the scheduled wiring runs without error and is
idempotent. The underlying selection logic is covered by the attestation
integration tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from celery.schedules import crontab
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestationUploadSession,
)
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework
from app.shared.models.audit_log import AuditLog
from app.workers.beat_schedule import BEAT_SCHEDULE
from app.workers.tasks.attestation_beat import (
    auto_release_attestations,
    escalate_attestation_disputes,
    expire_attestation_offers,
    expire_owner_consent,
    revoke_overdue_attestations,
    send_coi_resign_reminders,
)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Attestation tables exist before the beat tasks run."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def empty_attestation_state() -> AsyncIterator[None]:
    """Clear Attestation rows so every maintenance task sees a clean slate."""
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(AttestationDispute))
            await session.execute(delete(Attestation))
            await session.execute(delete(Framework))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _run_beat(task: object) -> dict[str, int]:
    """Run a Celery beat task in a worker thread and return its result dict.

    Disposes the shared async engine on either side of the thread hop so
    asyncpg connections stay bound to the loop that opened them.
    """
    await engine.dispose()
    result: dict[str, int] = await asyncio.to_thread(lambda: task.apply().get())
    await engine.dispose()
    return result


async def _seed_pending_owner_consent(*, created_at: datetime) -> UUID:
    """Create one pending owner-consent framework attestation at a chosen age."""
    async with async_session_factory() as session:
        async with session.begin():
            owner = User(
                email=f"consent-owner-{uuid4()}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="consent-owner",
                email_verified=True,
            )
            operator = User(
                email=f"consent-operator-{uuid4()}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="consent-operator",
                email_verified=True,
            )
            session.add_all([owner, operator])
            await session.flush()
            session.add_all(
                [
                    UserRole(
                        user_id=owner.id,
                        role="contributor",
                        approved_at=datetime.now(UTC),
                    ),
                    UserRole(
                        user_id=operator.id,
                        role="operator",
                        approved_at=datetime.now(UTC),
                    ),
                ]
            )
            framework = Framework(
                contributor_id=owner.id,
                title="Consent Window Framework",
                description="Published framework for owner-consent expiry tests.",
                status="published",
                category="compliance",
                tags=["consent"],
                price=Decimal("199.00"),
                license_types=["single_user"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            attestation = Attestation(
                target_type="framework",
                target_id=framework.id,
                requestor_id=operator.id,
                status="pending_owner_consent",
                review_type="quality",
                fee_amount=Decimal("500.00"),
                currency="USD",
                created_at=created_at,
            )
            session.add(attestation)
            await session.flush()
            return attestation.id


def test_expire_owner_consent_task_is_registered_in_beat_schedule() -> None:
    """Celery Beat includes the hourly owner-consent expiry task."""
    schedule = BEAT_SCHEDULE["expire-owner-consent-hourly"]

    assert schedule["task"] == (
        "app.workers.tasks.attestation_beat.expire_owner_consent"
    )
    assert schedule["schedule"] == 3600.0


def test_coi_resign_reminder_task_is_registered_in_beat_schedule() -> None:
    """Celery Beat includes the daily CoI re-sign reminder task."""
    schedule = BEAT_SCHEDULE["coi-resign-reminders-daily"]

    assert schedule["task"] == (
        "app.workers.tasks.attestation_beat.send_coi_resign_reminders"
    )
    assert schedule["schedule"] == crontab(hour=2, minute=0)


async def test_expire_attestation_offers_runs_cleanly_and_is_idempotent(
    migrated_database: None,
    empty_attestation_state: None,
) -> None:
    """The hourly offer-expiry task no-ops on an empty table, twice over."""
    del migrated_database, empty_attestation_state

    first = await _run_beat(expire_attestation_offers)
    second = await _run_beat(expire_attestation_offers)

    assert first == {"expired_count": 0}
    assert second == {"expired_count": 0}


async def test_expire_owner_consent_cancels_stale_requests(
    migrated_database: None,
    empty_attestation_state: None,
) -> None:
    """The hourly owner-consent expiry task cancels requests past the timeout."""
    del migrated_database, empty_attestation_state
    attestation_id = await _seed_pending_owner_consent(
        created_at=datetime.now(UTC) - timedelta(hours=73)
    )

    result = await _run_beat(expire_owner_consent)

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)

    assert result == {"cancelled_count": 1}
    assert attestation is not None
    assert attestation.status == "cancelled"
    assert attestation.closed_at is not None


async def test_expire_owner_consent_leaves_fresh_requests_untouched(
    migrated_database: None,
    empty_attestation_state: None,
) -> None:
    """The hourly owner-consent expiry task ignores recent requests."""
    del migrated_database, empty_attestation_state
    attestation_id = await _seed_pending_owner_consent(created_at=datetime.now(UTC))

    result = await _run_beat(expire_owner_consent)

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)

    assert result == {"cancelled_count": 0}
    assert attestation is not None
    assert attestation.status == "pending_owner_consent"
    assert attestation.closed_at is None


async def test_revoke_overdue_attestations_runs_cleanly(
    migrated_database: None,
    empty_attestation_state: None,
) -> None:
    """The overdue-revocation task no-ops when no Attestations are overdue."""
    del migrated_database, empty_attestation_state

    result = await _run_beat(revoke_overdue_attestations)

    assert result == {"revoked_count": 0}


async def test_auto_release_attestations_runs_cleanly(
    migrated_database: None,
    empty_attestation_state: None,
) -> None:
    """The auto-release task no-ops when no reports are past their window."""
    del migrated_database, empty_attestation_state

    result = await _run_beat(auto_release_attestations)

    assert result == {"released_count": 0}


async def test_escalate_attestation_disputes_runs_cleanly(
    migrated_database: None,
    empty_attestation_state: None,
) -> None:
    """The dispute-escalation task no-ops when no disputes are stale."""
    del migrated_database, empty_attestation_state

    result = await _run_beat(escalate_attestation_disputes)

    assert result == {"escalated_count": 0}


async def test_send_coi_resign_reminders_runs_cleanly(
    migrated_database: None,
    empty_attestation_state: None,
) -> None:
    """The daily CoI reminder task no-ops when no Attestor profiles are due."""
    del migrated_database, empty_attestation_state

    result = await _run_beat(send_coi_resign_reminders)

    assert result == {"reminded_count": 0}
