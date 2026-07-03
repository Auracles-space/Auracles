"""Celery tasks for organization invitation emails."""

from typing import Any

from loguru import logger

from app.integrations.resend import PermanentEmailError
from app.integrations.resend import send_org_invitation_email as send_via_resend
from app.workers.celery_app import app


@app.task(bind=True, max_retries=5, rate_limit="2/s")  # type: ignore[untyped-decorator]
def send_org_invitation(
    self: Any,
    email: str,
    org_name: str,
    role: str,
    token: str,
) -> None:
    """Send one organization invitation email."""
    log = logger.bind(
        module="organizations",
        action="send_org_invitation",
        task_id=self.request.id,
    )
    log.info("task_started")
    try:
        send_via_resend(email=email, org_name=org_name, role=role, token=token)
    except PermanentEmailError as exc:
        log.error("task_failed_permanent", error=str(exc))
        return
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed")
