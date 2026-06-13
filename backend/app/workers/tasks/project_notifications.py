"""Project notification fanout Celery tasks.

Project services call `dispatch_project_notification` after committing their
own domain state. The task creates the durable in-app notification first, then
fans out to Redis pub/sub and email only when the user's notification
preferences allow that channel.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.auth.models import User
from app.modules.notifications import preferences as notification_preferences
from app.modules.notifications import service as notification_service
from app.modules.realtime.pubsub import publish_to_channel
from app.workers.async_runner import run_async
from app.workers.celery_app import app
from app.workers.tasks.notifications import send_project_notification_email


async def _dispatch_project_notification_impl(
    *,
    user_id: str,
    notification_type: str,
    title: str,
    body: str,
    payload: dict[str, Any] | None = None,
    link: str | None = None,
    dedupe_key: str | None = None,
) -> dict[str, Any]:
    """Create a notification and dispatch per-channel fanout when enabled."""
    parsed_user_id = UUID(user_id)
    async with async_session_factory() as db:
        async with db.begin():
            user = await db.scalar(select(User).where(User.id == parsed_user_id))
            if user is None:
                raise ValueError("Notification user not found.")

            user_email = user.email
            in_app_enabled = await notification_preferences.should_deliver(
                db=db,
                user_id=parsed_user_id,
                notification_type=notification_type,
                channel="in_app",
            )
            email_enabled = await notification_preferences.should_deliver(
                db=db,
                user_id=parsed_user_id,
                notification_type=notification_type,
                channel="email",
            )

            if not in_app_enabled and not email_enabled:
                return {
                    "status": "suppressed",
                    "user_id": user_id,
                    "type": notification_type,
                }

            notification_id: UUID | None = None
            if in_app_enabled:
                notification = await notification_service.create_notification(
                    db=db,
                    user_id=parsed_user_id,
                    notification_type=notification_type,
                    title=title,
                    body=body,
                    link=link,
                    payload=payload,
                    dedupe_key=dedupe_key,
                )
                if notification is None:
                    return {
                        "status": "duplicate",
                        "user_id": user_id,
                        "type": notification_type,
                    }
                notification_id = notification.id

    if notification_id is not None:
        event_payload = {
            "id": str(notification_id),
            "type": notification_type,
            "title": title,
            "body": body,
            "link": link,
            "payload": payload,
        }
        await publish_to_channel(
            f"user:{parsed_user_id}",
            "notification_created",
            event_payload,
        )
    if email_enabled:
        send_project_notification_email.delay(
            email=user_email,
            title=title,
            body=body,
            link=link,
        )
    return {
        "status": "dispatched" if notification_id is not None else "in_app_suppressed",
        "notification_id": (
            str(notification_id) if notification_id is not None else None
        ),
        "user_id": user_id,
        "type": notification_type,
    }


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def dispatch_project_notification(
    self: Any,
    *,
    user_id: str,
    notification_type: str,
    title: str,
    body: str,
    payload: dict[str, Any] | None = None,
    link: str | None = None,
    dedupe_key: str | None = None,
) -> dict[str, Any]:
    """Create and fan out a project notification."""
    log = logger.bind(
        module="notifications",
        action="dispatch_project_notification",
        task_id=self.request.id,
        user_id=user_id,
        notification_type=notification_type,
    )
    log.info("task_started")
    try:
        result = run_async(
            _dispatch_project_notification_impl(
                user_id=user_id,
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
