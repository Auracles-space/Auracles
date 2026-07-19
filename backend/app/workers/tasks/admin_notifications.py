"""Admin-review notification fan-out Celery task.

Admins are a role, not a single account, so events that land in an admin
review queue cannot address one ``user_id``. This task resolves every account
holding the admin role and creates one durable notification per admin, reusing
the per-user project-notification dispatch impl for channel gating, realtime
fanout, email, and per-admin deduplication.

Callers enqueue this via
``app.modules.admin.notifications.notify_admins_review_pending`` after
committing their own domain state.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.auth.models import UserRole
from app.workers.async_runner import run_async
from app.workers.celery_app import app
from app.workers.tasks.project_notifications import (
    _dispatch_project_notification_impl,
)


async def _resolve_admin_ids() -> list[UUID]:
    """Return the distinct user ids of every account holding the admin role."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(UserRole.user_id).where(UserRole.role == "admin").distinct()
        )
        return list(result.scalars().all())


async def _dispatch_admin_notification_impl(
    *,
    notification_type: str,
    title: str,
    body: str,
    payload: dict[str, Any] | None,
    link: str | None,
    dedupe_key: str | None,
) -> dict[str, Any]:
    """Create one notification per admin for a single review-pending event."""
    admin_ids = await _resolve_admin_ids()
    for admin_id in admin_ids:
        # Suffix the shared dedupe base with the admin id so each admin gets
        # exactly one row while re-fired events stay idempotent per admin.
        per_admin_dedupe = (
            f"{dedupe_key}:{admin_id}" if dedupe_key is not None else None
        )
        await _dispatch_project_notification_impl(
            user_id=str(admin_id),
            notification_type=notification_type,
            title=title,
            body=body,
            payload=payload,
            link=link,
            dedupe_key=per_admin_dedupe,
        )
    return {"status": "dispatched", "admin_count": len(admin_ids)}


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def dispatch_admin_notification(
    self: Any,
    *,
    notification_type: str,
    title: str,
    body: str,
    payload: dict[str, Any] | None = None,
    link: str | None = None,
    dedupe_key: str | None = None,
) -> dict[str, Any]:
    """Fan out one review-pending notification to every admin account."""
    log = logger.bind(
        module="admin",
        action="dispatch_admin_notification",
        task_id=self.request.id,
        notification_type=notification_type,
    )
    log.info("task_started")
    try:
        result = run_async(
            _dispatch_admin_notification_impl(
                notification_type=notification_type,
                title=title,
                body=body,
                payload=payload,
                link=link,
                dedupe_key=dedupe_key,
            )
        )
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
