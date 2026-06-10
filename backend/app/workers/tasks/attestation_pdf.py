"""Celery tasks for rendering published Attestation report PDFs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from jinja2 import Environment
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import aliased
from weasyprint import HTML  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.attestation.models import Attestation
from app.modules.auth.models import User
from app.workers.async_runner import run_async
from app.workers.celery_app import app

REPORT_TEMPLATE = Environment(autoescape=True).from_string(
    """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <style>
          body { font-family: sans-serif; color: #171717; line-height: 1.5; }
          h1 { font-size: 28px; margin-bottom: 6px; }
          h2 { font-size: 18px; margin-top: 24px; }
          .muted { color: #5f6368; }
          .badge {
            display: inline-block;
            padding: 4px 8px;
            border: 1px solid #d7d3cc;
            border-radius: 4px;
            font-size: 12px;
            text-transform: uppercase;
          }
          .block {
            border-top: 1px solid #d7d3cc;
            padding-top: 12px;
            white-space: pre-wrap;
          }
        </style>
      </head>
      <body>
        <h1>Auracles Attestation Report</h1>
        <p class="muted">Attestation {{ attestation_id }}</p>
        <p class="badge">{{ visibility_label }}</p>
        <h2>Outcome</h2>
        <p>{{ outcome }}</p>
        <h2>Target</h2>
        <p>{{ target_type }} · {{ target_id }}</p>
        <h2>Requestor</h2>
        <p>{{ requestor_name }} &lt;{{ requestor_email }}&gt;</p>
        <h2>Attestor</h2>
        <p>{{ attestor_name }} &lt;{{ attestor_email }}&gt;</p>
        <h2>Summary</h2>
        <div class="block">{{ summary }}</div>
        <h2>Scope</h2>
        <div class="block">{{ scope }}</div>
        <h2>Evidence</h2>
        <div class="block">{{ evidence_references }}</div>
        <p class="muted">Issued at {{ issued_at }}</p>
      </body>
    </html>
    """
)


def _attestation_report_key(attestation_id: UUID | str) -> str:
    """Return the deterministic S3 key for an Attestation report PDF."""
    return f"attestation-reports/{attestation_id}/report.pdf"


async def _render_attestation_report_pdf(attestation_id: str) -> tuple[str, bytes]:
    """Render an Attestation report PDF and return its S3 key plus bytes."""
    parsed_attestation_id = UUID(attestation_id)
    requestor = aliased(User)
    attestor = aliased(User)
    async with async_session_factory() as db:
        row = await db.execute(
            select(Attestation, requestor, attestor)
            .join(requestor, requestor.id == Attestation.requestor_id)
            .join(attestor, attestor.id == Attestation.attestor_id)
            .where(
                Attestation.id == parsed_attestation_id,
                Attestation.status.in_(("report_submitted", "released", "closed")),
            )
        )
        report_row = row.one_or_none()
        if report_row is None:
            raise ValueError("Attestation report not found.")
        attestation, requestor_user, attestor_user = report_row
        if (
            attestation.summary is None
            or attestation.scope is None
            or attestation.outcome is None
            or attestation.issued_at is None
        ):
            raise ValueError("Attestation report is incomplete.")

    html = REPORT_TEMPLATE.render(
        attestation_id=str(attestation.id),
        visibility_label=(
            "pending acceptance"
            if attestation.status == "report_submitted"
            else attestation.status.replace("_", " ")
        ),
        outcome=attestation.outcome,
        target_type=attestation.target_type,
        target_id=str(attestation.target_id),
        requestor_name=requestor_user.display_name,
        requestor_email=requestor_user.email,
        attestor_name=attestor_user.display_name,
        attestor_email=attestor_user.email,
        summary=attestation.summary,
        scope=attestation.scope,
        evidence_references=attestation.evidence_references or {},
        issued_at=attestation.issued_at.isoformat(),
    )
    pdf_bytes = HTML(string=html).write_pdf()
    return attestation.report_key or _attestation_report_key(attestation.id), pdf_bytes


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def render_attestation_report_pdf(self: Any, attestation_id: str) -> dict[str, str]:
    """Generate and upload an Attestation report PDF to private report storage."""
    log = logger.bind(
        module="attestation",
        action="render_attestation_report_pdf",
        task_id=self.request.id,
        attestation_id=attestation_id,
    )
    log.info("task_started")
    try:
        report_key, pdf_bytes = run_async(
            _render_attestation_report_pdf(attestation_id)
        )
        settings = get_settings()
        s3.storage.upload_bytes(
            settings.s3_reports_bucket,
            report_key,
            pdf_bytes,
            "application/pdf",
        )
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    result = {
        "attestation_id": attestation_id,
        "report_key": report_key,
        "status": "report_generated",
    }
    log.info("task_completed", result=result)
    return result
