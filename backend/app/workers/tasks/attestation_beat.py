"""Scheduled Attestation maintenance tasks for cohort offer handling."""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.core.database import async_session_factory
from app.modules.attestation import matching_service
from app.workers.async_runner import run_async
from app.workers.celery_app import app


async def _expire_attestation_offers() -> int:
    """Expire stale Attestation offers and advance exhausted cohorts."""
    async with async_session_factory() as db:
        return await matching_service.expire_stale_offers(db)


async def _revoke_overdue_attestations() -> int:
    """Revoke accepted Attestations whose completion SLA has elapsed."""
    async with async_session_factory() as db:
        return await matching_service.revoke_overdue_attestations(db)


@app.task(bind=True)  # type: ignore[untyped-decorator]
def expire_attestation_offers(self: Any) -> dict[str, int]:
    """Celery wrapper for hourly Attestation offer expiry."""
    log = logger.bind(
        module="attestation",
        action="expire_attestation_offers",
        task_id=self.request.id,
    )
    log.info("task_started")
    expired_count = run_async(_expire_attestation_offers())
    result = {"expired_count": expired_count}
    log.info("task_completed", result=result)
    return result


@app.task(bind=True)  # type: ignore[untyped-decorator]
def revoke_overdue_attestations(self: Any) -> dict[str, int]:
    """Celery wrapper for hourly overdue Attestation revocation."""
    log = logger.bind(
        module="attestation",
        action="revoke_overdue_attestations",
        task_id=self.request.id,
    )
    log.info("task_started")
    revoked_count = run_async(_revoke_overdue_attestations())
    result = {"revoked_count": revoked_count}
    log.info("task_completed", result=result)
    return result
