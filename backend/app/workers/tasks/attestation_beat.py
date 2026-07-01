"""Scheduled Attestation maintenance tasks for cohort offers and workspace SLAs."""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.core.database import async_session_factory
from app.modules.attestation import (
    clarification_service,
    dispute_service,
    matching_service,
    release_service,
)
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


async def _expire_attestation_clarifications() -> int:
    """Close clarifications whose requestor response window has elapsed."""
    async with async_session_factory() as db:
        return await clarification_service.expire_clarifications(db)


async def _expire_owner_consent() -> int:
    """Cancel operator-initiated requests past their owner-consent window."""
    async with async_session_factory() as db:
        return await matching_service.expire_owner_consent(db)


async def _auto_release_attestations() -> int:
    """Release report-submitted Attestations past their dispute window."""
    async with async_session_factory() as db:
        return await release_service.auto_release_attestations(db)


async def _escalate_attestation_disputes() -> int:
    """Flag Attestation disputes that missed their resolution SLA."""
    async with async_session_factory() as db:
        return await dispute_service.escalate_attestation_disputes(db)


async def _send_coi_resign_reminders() -> int:
    """Send CoI re-sign reminders for expiring or lapsed Attestor declarations."""
    async with async_session_factory() as db:
        return await matching_service.send_coi_resign_reminders(db)


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


@app.task(bind=True)  # type: ignore[untyped-decorator]
def expire_attestation_clarifications(self: Any) -> dict[str, int]:
    """Celery wrapper for hourly clarification expiry."""
    log = logger.bind(
        module="attestation",
        action="expire_attestation_clarifications",
        task_id=self.request.id,
    )
    log.info("task_started")
    expired_count = run_async(_expire_attestation_clarifications())
    result = {"expired_count": expired_count}
    log.info("task_completed", result=result)
    return result


@app.task(bind=True)  # type: ignore[untyped-decorator]
def expire_owner_consent(self: Any) -> dict[str, int]:
    """Celery wrapper for hourly owner-consent expiry."""
    log = logger.bind(
        module="attestation",
        action="expire_owner_consent",
        task_id=self.request.id,
    )
    log.info("task_started")
    cancelled_count = run_async(_expire_owner_consent())
    result = {"cancelled_count": cancelled_count}
    log.info("task_completed", result=result)
    return result


@app.task(bind=True)  # type: ignore[untyped-decorator]
def auto_release_attestations(self: Any) -> dict[str, int]:
    """Celery wrapper for hourly Attestation report auto-release."""
    log = logger.bind(
        module="attestation",
        action="auto_release_attestations",
        task_id=self.request.id,
    )
    log.info("task_started")
    released_count = run_async(_auto_release_attestations())
    result = {"released_count": released_count}
    log.info("task_completed", result=result)
    return result


@app.task(bind=True)  # type: ignore[untyped-decorator]
def escalate_attestation_disputes(self: Any) -> dict[str, int]:
    """Celery wrapper for hourly Attestation dispute escalation."""
    log = logger.bind(
        module="attestation",
        action="escalate_attestation_disputes",
        task_id=self.request.id,
    )
    log.info("task_started")
    escalated_count = run_async(_escalate_attestation_disputes())
    result = {"escalated_count": escalated_count}
    log.info("task_completed", result=result)
    return result


@app.task(bind=True)  # type: ignore[untyped-decorator]
def send_coi_resign_reminders(self: Any) -> dict[str, int]:
    """Celery wrapper for the daily CoI re-sign reminder sweep."""
    log = logger.bind(
        module="attestation",
        action="send_coi_resign_reminders",
        task_id=self.request.id,
    )
    log.info("task_started")
    reminded_count = run_async(_send_coi_resign_reminders())
    result = {"reminded_count": reminded_count}
    log.info("task_completed", result=result)
    return result
