"""Beat tasks for annual attestor earnings summaries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from loguru import logger

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.invoicing.annual import (
    _annual_earner_ids,
    _annual_org_earner_ids,
    annual_line_items,
    annual_org_line_items,
    annual_org_summary_key,
    annual_summary_key,
    attestor_name,
    org_name,
    org_owner_id,
    render_annual_summary_pdf,
)
from app.workers.async_runner import run_async
from app.workers.celery_app import app
from app.workers.tasks.project_notifications import dispatch_project_notification


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def generate_annual_earnings_summary(
    self: Any,
    attestor_id: str,
    year: int,
) -> dict[str, str | int]:
    """Render and upload one attestor's annual earnings summary."""
    log = logger.bind(
        module="invoicing",
        action="generate_annual_earnings_summary",
        task_id=self.request.id,
        attestor_id=attestor_id,
        year=year,
    )
    log.info("task_started")
    parsed_attestor_id = UUID(attestor_id)
    try:

        async def _build_summary() -> tuple[
            list[dict[str, str]],
            dict[str, str | int],
            str,
        ]:
            async with async_session_factory() as db:
                line_items, totals = await annual_line_items(
                    db,
                    attestor_id=parsed_attestor_id,
                    year=year,
                )
                name = await attestor_name(db, parsed_attestor_id)
                return line_items, totals, name

        line_items, totals, name = run_async(_build_summary())
        if not line_items:
            skipped_result: dict[str, str | int] = {
                "attestor_id": attestor_id,
                "year": year,
                "status": "skipped",
            }
            log.info("task_completed", result=skipped_result)
            return skipped_result

        key = annual_summary_key(parsed_attestor_id, year)
        pdf_bytes = render_annual_summary_pdf(
            attestor_name=name,
            year=year,
            line_items=line_items,
            totals=totals,
        )
        settings = get_settings()
        s3.storage.upload_bytes(
            settings.s3_reports_bucket,
            key,
            pdf_bytes,
            "application/pdf",
        )
        dispatch_project_notification.delay(
            user_id=attestor_id,
            notification_type="attestation_annual_summary_ready",
            title=f"Your {year} earnings summary is ready",
            body=f"Your annual attestation earnings summary for {year} is ready.",
            link="/attestations",
            dedupe_key=f"attestation_annual_summary:{attestor_id}:{year}",
        )
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc

    result: dict[str, str | int] = {
        "attestor_id": attestor_id,
        "year": year,
        "status": "generated",
    }
    log.info("task_completed", result=result)
    return result


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def generate_annual_org_earnings_summary(
    self: Any,
    org_id: str,
    year: int,
) -> dict[str, str | int]:
    """Render and upload one organization's annual earnings summary."""
    log = logger.bind(
        module="invoicing",
        action="generate_annual_org_earnings_summary",
        task_id=self.request.id,
        org_id=org_id,
        year=year,
    )
    log.info("task_started")
    parsed_org_id = UUID(org_id)
    try:

        async def _build_summary() -> tuple[
            list[dict[str, str]],
            dict[str, str | int],
            str,
            UUID | None,
        ]:
            async with async_session_factory() as db:
                line_items, totals = await annual_org_line_items(
                    db,
                    org_id=parsed_org_id,
                    year=year,
                )
                name = await org_name(db, parsed_org_id)
                owner_id = await org_owner_id(db, parsed_org_id)
                return line_items, totals, name, owner_id

        line_items, totals, name, owner_id = run_async(_build_summary())
        if not line_items:
            skipped_result: dict[str, str | int] = {
                "org_id": org_id,
                "year": year,
                "status": "skipped",
            }
            log.info("task_completed", result=skipped_result)
            return skipped_result

        key = annual_org_summary_key(parsed_org_id, year)
        pdf_bytes = render_annual_summary_pdf(
            attestor_name=name,
            year=year,
            line_items=line_items,
            totals=totals,
        )
        settings = get_settings()
        s3.storage.upload_bytes(
            settings.s3_reports_bucket,
            key,
            pdf_bytes,
            "application/pdf",
        )
        if owner_id is not None:
            dispatch_project_notification.delay(
                user_id=str(owner_id),
                notification_type="attestation_annual_summary_ready",
                title=f"Your {year} earnings summary is ready",
                body=f"Your organization's {year} attestation earnings "
                "summary is ready.",
                link="/orgs",
                dedupe_key=f"attestation_annual_summary:org:{org_id}:{year}",
            )
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc

    result: dict[str, str | int] = {
        "org_id": org_id,
        "year": year,
        "status": "generated",
    }
    log.info("task_completed", result=result)
    return result


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def generate_annual_earnings_summaries(self: Any) -> dict[str, int]:
    """Render prior-year annual earnings summaries for all earners."""
    year = datetime.now(UTC).year - 1
    log = logger.bind(
        module="invoicing",
        action="generate_annual_earnings_summaries",
        task_id=self.request.id,
        year=year,
    )
    log.info("task_started")
    try:
        attestor_ids = run_async(_annual_earner_ids(year))
        for attestor_id in attestor_ids:
            generate_annual_earnings_summary.delay(str(attestor_id), year)
        org_ids = run_async(_annual_org_earner_ids(year))
        for org_id in org_ids:
            generate_annual_org_earnings_summary.delay(str(org_id), year)
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc

    earner_count = len(attestor_ids) + len(org_ids)
    result: dict[str, int] = {
        "year": year,
        "earner_count": earner_count,
        "queued_count": earner_count,
    }
    log.info("task_completed", result=result)
    return result
