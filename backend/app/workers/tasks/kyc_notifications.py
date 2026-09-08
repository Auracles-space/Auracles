"""Identity-verification verdict email fanout.

The KYC services write their durable in-app notification inside the same
transaction as the verdict, so it is never lost. Email is the channel that
actually reaches the applicant, and it is dispatched here — after that
transaction commits — so a slow or failing mail provider can never roll back a
verification decision.

Maps to: FR-AUTH-009, FR-SET-011.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.database import async_session_factory
from app.integrations.resend import send_kyc_verdict_email
from app.modules.auth.models import User
from app.modules.notifications import preferences as notification_preferences
from app.workers.async_runner import run_async
from app.workers.celery_app import app


async def _send_kyc_verdict_impl(*, user_id: str, verified: bool) -> dict[str, Any]:
    """Look up the applicant and email them the verdict when allowed."""
    parsed_user_id = UUID(user_id)
    notification_type = "kyc_verified" if verified else "kyc_rejected"

    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.id == parsed_user_id))
        if user is None:
            # A deleted or anonymised account is a normal outcome here, not a
            # fault: retrying would never succeed.
            return {"status": "unknown_user", "user_id": user_id}
        email = user.email
        email_enabled = await notification_preferences.should_deliver(
            db=db,
            user_id=parsed_user_id,
            notification_type=notification_type,
            channel="email",
        )

    if not email_enabled:
        return {"status": "suppressed", "user_id": user_id, "type": notification_type}

    send_kyc_verdict_email(email=email, verified=verified)
    return {"status": "sent", "user_id": user_id, "type": notification_type}


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def send_kyc_verdict_notification(
    self: Any,
    *,
    user_id: str,
    verified: bool,
) -> dict[str, Any]:
    """Email an applicant the outcome of their identity verification."""
    log = logger.bind(
        module="settings",
        action="send_kyc_verdict_notification",
        task_id=self.request.id,
        user_id=user_id,
    )
    log.info("task_started")
    try:
        result = run_async(
            _send_kyc_verdict_impl(user_id=user_id, verified=verified)
        )
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
