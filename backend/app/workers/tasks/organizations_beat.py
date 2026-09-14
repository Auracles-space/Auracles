"""Celery Beat tasks for organization invitation expiry.

Marks pending invitations past their expires_at timestamp as 'expired'
in a single daily sweep and tells invitees who hold an account that the
offer lapsed. Runs idempotently — re-running on an empty result set is a
safe no-op.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import func, select, update

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.modules.auth.models import User
from app.modules.organizations import notifications as org_notifications
from app.modules.organizations.models import Organization, OrgInvitation
from app.workers.async_runner import run_async
from app.workers.celery_app import app


async def _expire_pending_invitations_impl() -> dict[str, int]:
    """Flip all pending invitations past their deadline to 'expired'.

    Returns:
        Dict with 'expired_count' for observability logging.
    """
    now = datetime.now(UTC)
    # (invitee user id, org id, org name) for invitees who hold an account,
    # collected inside the transaction and dispatched after it commits.
    to_notify: list[tuple[UUID, UUID, str]] = []
    async with async_session_factory() as db:
        async with db.begin():
            # Fetch pending invitations past their expiry window
            due = (
                await db.execute(
                    select(
                        OrgInvitation.id,
                        OrgInvitation.org_id,
                        Organization.name,
                        User.id,
                    )
                    .join(Organization, Organization.id == OrgInvitation.org_id)
                    .join(
                        User,
                        func.lower(User.email) == func.lower(OrgInvitation.email),
                        isouter=True,
                    )
                    .where(
                        OrgInvitation.status == "pending",
                        OrgInvitation.expires_at < now,
                    )
                )
            ).all()
            due_ids = [invitation_id for invitation_id, _, _, _ in due]
            if not due_ids:
                return {"expired_count": 0}
            to_notify = [
                (user_id, org_id, org_name)
                for _, org_id, org_name, user_id in due
                if user_id is not None
            ]

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
    for user_id, org_id, org_name in to_notify:
        org_notifications.notify_invitation_expired(
            user_id, org_id=org_id, org_name=org_name
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
