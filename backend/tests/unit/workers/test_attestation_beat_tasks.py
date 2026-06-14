"""Scheduled Attestation beat task tests.

Covers the Celery wrappers in ``app/workers/tasks/attestation_beat.py`` and
their thin async helpers end-to-end. The wrappers run their work inside the
worker's own event loop via ``run_async``; the tests cross event loops with
``asyncio.to_thread`` and dispose the shared async engine around each crossing
so pooled asyncpg connections are never reused by a different loop.

The four maintenance tasks each select stale/overdue rows. Against an empty
Attestation table they perform a clean no-op pass, which exercises every line
of the beat module and proves the scheduled wiring runs without error and is
idempotent. The underlying selection logic is covered by the attestation
integration tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.main import app
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestationUploadSession,
)
from app.workers.tasks.attestation_beat import (
    auto_release_attestations,
    escalate_attestation_disputes,
    expire_attestation_offers,
    revoke_overdue_attestations,
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
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(AttestationDispute))
            await session.execute(delete(Attestation))
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
