"""Celery task that records one unmet-demand search.

Recording runs off the request path. A search must never fail, or slow down,
because demand analytics did — so the endpoint queues and returns, and every
failure here is the task's problem alone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from loguru import logger

from app.core.database import async_session_factory
from app.modules.demand import service as demand_service
from app.workers.async_runner import run_async
from app.workers.celery_app import app


async def _record(
    *,
    query: str | None,
    filters: dict[str, Any],
    searcher_id: str | None,
    searcher_key: str | None,
) -> None:
    """Write one search gap in its own session."""
    async with async_session_factory() as session:
        await demand_service.record_search_gap(
            session,
            query=query,
            filters=filters,
            searcher_id=UUID(searcher_id) if searcher_id else None,
            searcher_key=searcher_key,
            now=datetime.now(UTC),
        )
        await session.commit()


@app.task(bind=True)  # type: ignore[untyped-decorator]
def record_search_gap_task(
    self: Any,
    *,
    query: str | None,
    filters: dict[str, Any],
    searcher_id: str | None,
    searcher_key: str | None,
) -> None:
    """Record one zero-result Explore search.

    Idempotency is deliberately not enforced: two identical searches by the
    same person on the same day are two rows, and the rollup counts distinct
    searchers rather than rows, so a retry cannot inflate demand.

    Args:
        self: Celery task instance.
        query: Free-text query as typed, or None for a filters-only search.
        filters: Filters that were set on the search.
        searcher_id: Stringified user id when signed in, else None.
        searcher_key: Rotating anonymous key when not signed in, else None.
    """
    log = logger.bind(
        module="demand",
        action="record_search_gap",
        task_id=self.request.id,
    )
    try:
        run_async(
            _record(
                query=query,
                filters=filters,
                searcher_id=searcher_id,
                searcher_key=searcher_key,
            )
        )
    except Exception as exc:  # noqa: BLE001 - retried below, never swallowed
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc


async def _roll_up_and_sweep() -> dict[str, int]:
    """Recount the current and previous month, then drop expired raw rows.

    The previous month is re-rolled because a run just after midnight on the
    first would otherwise leave that month counted without its final hours.
    """
    now = datetime.now(UTC)
    previous = (now.date().replace(day=1) - timedelta(days=1)).replace(day=1)
    async with async_session_factory() as session:
        signals = await demand_service.roll_up_demand(session, period=now.date())
        signals += await demand_service.roll_up_demand(session, period=previous)
        swept = await demand_service.sweep_expired_gaps(session, now=now)
        await session.commit()
    return {"signals": signals, "swept": swept}


@app.task(bind=True)  # type: ignore[untyped-decorator]
def roll_up_demand_signals(self: Any) -> dict[str, int]:
    """Recount demand and expire raw search rows past their retention window."""
    log = logger.bind(
        module="demand",
        action="roll_up_demand_signals",
        task_id=self.request.id,
    )
    log.info("task_started")
    result = run_async(_roll_up_and_sweep())
    log.info("task_completed", result=result)
    return result
