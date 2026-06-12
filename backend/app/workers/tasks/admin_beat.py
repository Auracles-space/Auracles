"""Scheduled admin analytics maintenance tasks.

Builds frozen UTC daily analytics snapshots that back dashboard trend charts
and CSV export without recomputing historical aggregates on every request.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from app.core.database import async_session_factory
from app.modules.admin import service as admin_service
from app.modules.admin.models import AnalyticsDailySnapshot
from app.workers.async_runner import run_async
from app.workers.celery_app import app


async def _snapshot_daily_analytics_impl(
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Upsert the frozen analytics row for the prior UTC day."""
    effective_now = (now or datetime.now(UTC)).astimezone(UTC)
    snapshot_date = (effective_now - timedelta(days=1)).date()
    async with async_session_factory() as db:
        async with db.begin():
            payload = await admin_service.compute_daily_snapshot_payload(
                db,
                snapshot_date=snapshot_date,
            )
            snapshot = await db.get(
                AnalyticsDailySnapshot,
                snapshot_date,
                with_for_update=True,
            )
            created = snapshot is None
            if snapshot is None:
                snapshot = AnalyticsDailySnapshot(
                    snapshot_date=snapshot_date,
                    gmv_total=payload["gmv_total"],
                    gmv_by_source=payload["gmv_by_source"],
                    active_users=int(payload["active_users"]),
                    new_registrations=int(payload["new_registrations"]),
                    frameworks_published=int(payload["frameworks_published"]),
                    attestations_issued=int(payload["attestations_issued"]),
                    disputes_open=int(payload["disputes_open"]),
                    computed_at=effective_now,
                )
                db.add(snapshot)
            else:
                snapshot.gmv_total = payload["gmv_total"]
                snapshot.gmv_by_source = payload["gmv_by_source"]
                snapshot.active_users = int(payload["active_users"])
                snapshot.new_registrations = int(payload["new_registrations"])
                snapshot.frameworks_published = int(payload["frameworks_published"])
                snapshot.attestations_issued = int(payload["attestations_issued"])
                snapshot.disputes_open = int(payload["disputes_open"])
                snapshot.computed_at = effective_now
        return {
            "snapshot_date": snapshot_date.isoformat(),
            "created": created,
        }


@app.task(bind=True)  # type: ignore[untyped-decorator]
def snapshot_daily_analytics(self: Any) -> dict[str, object]:
    """Celery wrapper for the daily admin analytics snapshot job."""
    log = logger.bind(
        module="admin",
        action="snapshot_daily_analytics",
        task_id=self.request.id,
    )
    log.info("task_started")
    result = run_async(_snapshot_daily_analytics_impl())
    log.info("task_completed", result=result)
    return result
