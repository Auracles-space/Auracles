"""Scheduled financial reconciliation tasks.

Celery Beat invokes this module to close out money that provider webhooks
left in an unresolved state.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.core.database import async_session_factory
from app.modules.financials.balance_floor import (
    BalanceFloorResult,
    check_platform_balance_floor,
)
from app.modules.financials.reconciliation import (
    ReconciliationResult,
    reconcile_pending_refunds,
)
from app.workers.async_runner import run_async
from app.workers.celery_app import app


async def _reconcile_pending_refunds() -> ReconciliationResult:
    """Run refund reconciliation inside one database transaction."""
    async with async_session_factory() as db:
        async with db.begin():
            return await reconcile_pending_refunds(db)


@app.task(bind=True)  # type: ignore[untyped-decorator]
def reconcile_pending_refunds_task(self: Any) -> ReconciliationResult:
    """Celery wrapper for hourly refund reconciliation.

    Idempotent: a refund resolved by an earlier run, or by the webhook, is
    excluded by the query rather than re-applied.
    """
    log = logger.bind(
        module="financials",
        action="reconcile_pending_refunds",
        task_id=self.request.id,
    )
    log.info("task_started")
    result = run_async(_reconcile_pending_refunds())
    log.info("task_completed", result=result)
    return result


async def _check_platform_balance_floor() -> BalanceFloorResult:
    """Run the balance floor check inside one database session."""
    async with async_session_factory() as db:
        return await check_platform_balance_floor(db)


@app.task(bind=True)  # type: ignore[untyped-decorator]
def check_platform_balance_floor_task(self: Any) -> BalanceFloorResult:
    """Celery wrapper for the hourly Paystack balance floor check.

    Read-only and idempotent: alerts dedupe per currency at the notification
    layer, so a floor still breached on the next run does not page again.
    """
    log = logger.bind(
        module="financials",
        action="check_platform_balance_floor",
        task_id=self.request.id,
    )
    log.info("task_started")
    result = run_async(_check_platform_balance_floor())
    log.info("task_completed", result=result)
    return result
