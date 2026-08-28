"""Scheduled financial reconciliation tasks.

Celery Beat invokes this module to close out money that provider webhooks
left in an unresolved state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import delete

from app.core.database import async_session_factory
from app.modules.financials.balance_floor import (
    BalanceFloorResult,
    check_platform_balance_floor,
)
from app.modules.financials.payout_sweeper import (
    PayoutSweepResult,
    requeue_stranded_payouts,
)
from app.modules.financials.reconciliation import (
    ReconciliationResult,
    reconcile_pending_refunds,
)
from app.modules.webhooks.models import WebhookEvent
from app.workers.async_runner import run_async
from app.workers.celery_app import app
from app.workers.tasks.payouts import process_payout


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
    """Run the balance floor check inside one database transaction.

    The transaction exists for the breach audit row; the check itself only
    reads.
    """
    async with async_session_factory() as db:
        async with db.begin():
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


# Providers stop retrying deliveries within days; rows past this window only
# grow the dedupe table. The durable money record lives in audit_logs and the
# financial_events ledger, never here.
WEBHOOK_EVENT_RETENTION = timedelta(days=90)


async def _prune_webhook_events() -> dict[str, int]:
    """Delete webhook event rows past the retention window."""
    cutoff = datetime.now(UTC) - WEBHOOK_EVENT_RETENTION
    async with async_session_factory() as db:
        async with db.begin():
            result = await db.execute(
                delete(WebhookEvent).where(WebhookEvent.received_at < cutoff)
            )
    return {"pruned": int(getattr(result, "rowcount", 0) or 0)}


@app.task(bind=True)  # type: ignore[untyped-decorator]
def prune_webhook_events_task(self: Any) -> dict[str, int]:
    """Celery wrapper for daily webhook-event pruning."""
    log = logger.bind(
        module="financials",
        action="prune_webhook_events",
        task_id=self.request.id,
    )
    log.info("task_started")
    result = run_async(_prune_webhook_events())
    log.info("task_completed", result=result)
    return result


async def _requeue_stranded_payouts() -> PayoutSweepResult:
    """Run the stranded-payout sweep inside one database session."""
    async with async_session_factory() as db:
        return await requeue_stranded_payouts(
            db,
            enqueue=lambda payout_id: process_payout.delay(payout_id),
        )


@app.task(bind=True)  # type: ignore[untyped-decorator]
def requeue_stranded_payouts_task(self: Any) -> PayoutSweepResult:
    """Celery wrapper for the hourly stranded-payout sweep.

    Idempotent: the processing worker returns untouched any payout that is
    no longer pending or already carries a provider reference, so a payout
    re-enqueued while merely slow is a no-op.
    """
    log = logger.bind(
        module="financials",
        action="requeue_stranded_payouts",
        task_id=self.request.id,
    )
    log.info("task_started")
    result = run_async(_requeue_stranded_payouts())
    log.info("task_completed", result=result)
    return result
