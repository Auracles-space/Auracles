"""Celery task running the one-off Paystack fee backfill.

The work lives in ``financials.provider_fee_backfill``; this wrapper runs it
off the request path and writes the completion audit row with the counts.
Rerunnable: charges that already have a fee are skipped.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.workers.async_runner import run_async
from app.workers.celery_app import app


async def _run_backfill(actor_id: str) -> dict[str, int]:
    """Run the backfill and audit its result."""
    # Imported here: the service module imports this task to dispatch it.
    from app.modules.financials.provider_fee_backfill import backfill_paystack_fees

    result = await backfill_paystack_fees()
    async with async_session_factory() as db:
        async with db.begin():
            await write_audit(
                db=db,
                actor_id=UUID(actor_id),
                action="provider_fee_backfill_completed",
                target_type="provider_fee",
                metadata={**result},
            )
    return {
        "checked": result["checked"],
        "recorded": result["recorded"],
        "failed": result["failed"],
    }


@app.task(bind=True, max_retries=0)  # type: ignore[untyped-decorator]
def backfill_provider_fees(self: Any, actor_id: str) -> dict[str, int]:
    """Backfill Paystack fees on settled charges that have none."""
    log = logger.bind(
        module="financials",
        action="backfill_provider_fees",
        task_id=self.request.id,
        user_id=actor_id,
    )
    log.info("task_started")
    result = run_async(_run_backfill(actor_id))
    log.info("task_completed", **result)
    return result
