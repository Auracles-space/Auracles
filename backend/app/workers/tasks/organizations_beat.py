"""Celery Beat tasks for organization invitation expiry.

Marks pending invitations past their expires_at timestamp as 'expired'
in a single daily sweep. Runs idempotently — re-running on an empty
result set is a safe no-op.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import select, update

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.modules.organizations.models import OrgInvitation
from app.workers.async_runner import run_async
from app.workers.celery_app import app


async def _expire_pending_invitations_impl() -> dict[str, int]:
    """Flip all pending invitations past their deadline to 'expired'.

    Returns:
        Dict with 'expired_count' for observability logging.
    """
    now = datetime.now(UTC)
    async with async_session_factory() as db:
        async with db.begin():
            # Fetch IDs of pending invitations past their expiry window
            due_ids = list(
                (
                    await db.scalars(
                        select(OrgInvitation.id).where(
                            OrgInvitation.status == "pending",
                            OrgInvitation.expires_at < now,
                        )
                    )
                ).all()
            )
            if not due_ids:
                return {"expired_count": 0}

            await db.execute(
                update(OrgInvitation)
                .where(OrgInvitation.id.in_(due_ids))
                .values(status="expired", responded_at=now)
            )
            # Audit each expiry for traceability
            for invitation_id in due_ids:
                await write_audit(
                    db=db,
                    actor_id=None,
                    action="org_invitation_expired",
                    target_type="org_invitation",
                    target_id=invitation_id,
                )
    return {"expired_count": len(due_ids)}


@app.task(bind=True)  # type: ignore[untyped-decorator]
def expire_pending_org_invitations(self: Any) -> dict[str, int]:
    """Celery wrapper for the daily org invitation expiry sweep."""
    log = logger.bind(
        module="organizations",
        action="expire_pending_org_invitations",
        task_id=self.request.id,
    )
    log.info("task_started")
    result = run_async(_expire_pending_invitations_impl())
    log.info("task_completed", result=result)
    return result
