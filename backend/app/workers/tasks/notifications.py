"""Notification Celery tasks.

Tasks in this module are idempotent dispatch wrappers around email providers.
They can be retried safely when the external provider is temporarily down.
"""

from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import func, select

from app.core.database import async_session_factory
from app.integrations.resend import (
    send_email_change_verification as send_email_change_via_resend,
)
from app.integrations.resend import send_new_device_email as send_new_device_via_resend
from app.integrations.resend import (
    send_password_reset_email as send_password_reset_via_resend,
)
from app.integrations.resend import (
    send_project_notification_email as send_project_notification_via_resend,
)
from app.integrations.resend import send_verification_email as send_via_resend
from app.modules.frameworks.models import License
from app.workers.async_runner import run_async
from app.workers.celery_app import app


@app.task(bind=True)  # type: ignore[untyped-decorator]
def send_verification_email(self: Any, email: str, token: str) -> None:
    """Send a registration verification email."""
    log = logger.bind(
        module="auth",
        action="send_verification_email",
        task_id=self.request.id,
    )
    log.info("task_started")
    try:
        send_via_resend(email=email, token=token)
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed")


@app.task(bind=True)  # type: ignore[untyped-decorator]
def send_password_reset_email(self: Any, email: str, token: str) -> None:
    """Send a password reset email."""
    log = logger.bind(
        module="auth",
        action="send_password_reset_email",
        task_id=self.request.id,
    )
    log.info("task_started")
    try:
        send_password_reset_via_resend(email=email, token=token)
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed")


@app.task(bind=True)  # type: ignore[untyped-decorator]
def send_email_change_verification(self: Any, email: str, token: str) -> None:
    """Send a new-account-email verification email."""
    log = logger.bind(
        module="settings",
        action="send_email_change_verification",
        task_id=self.request.id,
    )
    log.info("task_started")
    try:
        send_email_change_via_resend(email=email, token=token)
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed")


@app.task(bind=True)  # type: ignore[untyped-decorator]
def send_new_device_email(
    self: Any,
    email: str,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """Send a new-device login notification email."""
    log = logger.bind(
        module="auth",
        action="send_new_device_email",
        task_id=self.request.id,
    )
    log.info("task_started")
    try:
        send_new_device_via_resend(email=email, ip=ip, user_agent=user_agent)
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed")


@app.task(bind=True)  # type: ignore[untyped-decorator]
def send_project_notification_email(
    self: Any,
    *,
    email: str,
    title: str,
    body: str,
    link: str | None = None,
) -> None:
    """Send an off-session project notification email."""
    log = logger.bind(
        module="notifications",
        action="send_project_notification_email",
        task_id=self.request.id,
    )
    log.info("task_started")
    try:
        send_project_notification_via_resend(
            email=email,
            title=title,
            body=body,
            link=link,
        )
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed")


@app.task(bind=True)  # type: ignore[untyped-decorator]
def send_saved_search_alert_email(
    self: Any,
    *,
    email: str,
    saved_search_name: str,
    matches: list[dict[str, str]],
    link: str | None = None,
) -> None:
    """Send a saved-search digest email through the generic notification template."""
    log = logger.bind(
        module="notifications",
        action="send_saved_search_alert_email",
        task_id=self.request.id,
    )
    log.info("task_started", match_count=len(matches))
    try:
        match_lines = "\n".join(
            f"- {match['title']}: {match['link']}" for match in matches
        )
        send_project_notification_via_resend(
            email=email,
            title=f"New Auracles matches for {saved_search_name}",
            body=(
                "New Frameworks match your saved search.\n"
                f"\nSaved search: {saved_search_name}\n{match_lines}"
            ),
            link=link,
        )
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed")


async def _notify_licensees_of_new_version_impl(
    framework_id: str,
    new_version: str,
) -> dict[str, Any]:
    """Return active-license count for future new-version notifications."""
    parsed_framework_id = UUID(framework_id)
    async with async_session_factory() as db:
        active_license_count = await db.scalar(
            select(func.count(License.id)).where(
                License.framework_id == parsed_framework_id,
                License.status == "active",
            )
        )
    return {
        "framework_id": framework_id,
        "new_version": new_version,
        "active_license_count": int(active_license_count or 0),
    }


@app.task(bind=True)  # type: ignore[untyped-decorator]
def notify_licensees_of_new_version(
    self: Any,
    framework_id: str,
    new_version: str,
) -> dict[str, Any]:
    """Notify active licensees that a Framework has a new published version."""
    log = logger.bind(
        module="frameworks",
        action="notify_licensees_of_new_version",
        task_id=self.request.id,
        framework_id=framework_id,
    )
    log.info("task_started")
    try:
        result = run_async(
            _notify_licensees_of_new_version_impl(framework_id, new_version)
        )
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
