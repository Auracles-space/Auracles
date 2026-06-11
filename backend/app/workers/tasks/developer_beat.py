"""Scheduled Developer platform maintenance tasks.

Celery Beat invokes this module for Partner commission clearing, tier
recalculation, webhook retries, and future Developer data retention jobs.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.core.database import async_session_factory
from app.modules.developer import commission_service
from app.workers.async_runner import run_async
from app.workers.celery_app import app


async def _clear_partner_commissions() -> dict[str, int]:
    """Run Partner commission clearing inside one database transaction."""
    async with async_session_factory() as db:
        async with db.begin():
            return await commission_service.clear_partner_commissions(db)


async def _recompute_partner_tiers() -> dict[str, int]:
    """Run Partner tier recomputation inside one database transaction."""
    async with async_session_factory() as db:
        async with db.begin():
            return await commission_service.recompute_partner_tiers(db)


@app.task(bind=True)  # type: ignore[untyped-decorator]
def clear_partner_commissions(self: Any) -> dict[str, int]:
    """Celery wrapper for hourly Partner commission clearing."""
    log = logger.bind(
        module="developer",
        action="clear_partner_commissions",
        task_id=self.request.id,
    )
    log.info("task_started")
    result = run_async(_clear_partner_commissions())
    log.info("task_completed", result=result)
    return result


@app.task(bind=True)  # type: ignore[untyped-decorator]
def recompute_partner_tiers(self: Any) -> dict[str, int]:
    """Celery wrapper for monthly Partner tier recomputation."""
    log = logger.bind(
        module="developer",
        action="recompute_partner_tiers",
        task_id=self.request.id,
    )
    log.info("task_started")
    result = run_async(_recompute_partner_tiers())
    log.info("task_completed", result=result)
    return result
