"""Notification Celery tasks.

Tasks in this module are idempotent dispatch wrappers around email providers.
They can be retried safely when the external provider is temporarily down.
"""

from typing import Any

from loguru import logger

from app.integrations.resend import send_new_device_email as send_new_device_via_resend
from app.integrations.resend import (
    send_password_reset_email as send_password_reset_via_resend,
)
from app.integrations.resend import send_verification_email as send_via_resend
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
