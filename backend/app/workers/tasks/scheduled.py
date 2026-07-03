"""Scheduled maintenance tasks run by Celery Beat."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.modules.frameworks.models import License
from app.workers.async_runner import run_async
from app.workers.celery_app import app


async def _clear_expired_licenses() -> int:
    """Mark active licenses expired when their expiry timestamp has passed."""
    now = datetime.now(UTC)
    async with async_session_factory() as db:
        async with db.begin():
            licenses = (
                (
                    await db.execute(
                        select(License).where(
                            License.status == "active",
                            License.expires_at.is_not(None),
                            License.expires_at < now,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for license_row in licenses:
                license_row.status = "expired"
                await write_audit(
                    db=db,
                    actor_id=None,
                    action="license_expired",
                    target_type="license",
                    target_id=license_row.id,
                    metadata={
                        "framework_id": str(license_row.framework_id),
                        "operator_id": str(license_row.operator_id),
                    },
                )
            return len(licenses)


@app.task(bind=True)  # type: ignore[untyped-decorator]
def clear_expired_licenses(self: Any) -> dict[str, int]:
    """Expire licenses whose access window has elapsed."""
    log = logger.bind(
        module="financials",
        action="clear_expired_licenses",
        task_id=self.request.id,
    )
    log.info("task_started")
    expired_count = run_async(_clear_expired_licenses())
    result = {"expired_count": expired_count}
    log.info("task_completed", result=result)
    return result
