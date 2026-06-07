"""Notification Celery tasks.

Tasks in this module are idempotent dispatch wrappers around email providers.
They can be retried safely when the external provider is temporarily down.
"""

from typing import Any

from loguru import logger

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
