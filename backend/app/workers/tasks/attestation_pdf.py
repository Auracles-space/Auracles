"""Celery tasks for rendering published Attestation report PDFs."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from jinja2 import Environment
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.attestation import rubrics
from app.modules.attestation.models import (
    Attestation,
    AttestationAnnotation,
    AttestationRubricDimension,
    AttestationRubricMethodology,
    AttestationRubricScore,
)
from app.modules.auth.models import User
from app.modules.organizations.models import Organization, OrgAttestorProfile
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
          table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
          }
          th, td {
            text-align: left;
            padding: 8px 0;
            border-bottom: 1px solid #ece7df;
            vertical-align: top;
          }
          ul {
            padding-left: 18px;
          }
        </style>
      </head>
      <body>
        <h1>Auracles Attestation Report</h1>
        <p class="muted">Attestation {{ attestation_id }}</p>
        <p class="badge">{{ visibility_label }}</p>
        <h2>Target</h2>
        <p>{{ target_type }} · {{ target_id }}</p>
        <h2>Executive Summary</h2>
        <div class="block">{{ summary }}</div>
        <h2>Scope of Review</h2>
        <div class="block">{{ scope }}</div>
        <h2>Methodology</h2>
        <div class="block">{{ methodology }}</div>
        <h2>Dimension Scores</h2>
        <table>
          <thead>
            <tr>
              <th>Dimension</th>
              <th>Weight</th>
              <th>Score</th>
              <th>Comment</th>
            </tr>
          </thead>
          <tbody>
          {% for dimension in dimensions %}
            <tr>
              <td>{{ dimension.label }}</td>
              <td>{{ dimension.weight }}</td>
              <td>{{ dimension.score }}</td>
              <td>{{ dimension.comment }}</td>
            </tr>
          {% endfor %}
          </tbody>
        </table>
        <p><strong>Weighted overall score:</strong> {{ weighted_overall }}</p>
        <h2>Key Findings</h2>
        {% if findings %}
          {% for finding in findings %}
            <div class="block">
              <p>
                <strong>{{ finding.annotation_type }}</strong> ·
                {{ finding.location_label }}
              </p>
              {% if finding.quoted_excerpt %}
                <p>{{ finding.quoted_excerpt }}</p>
              {% endif %}
              <p>{{ finding.comment }}</p>
            </div>
          {% endfor %}
        {% else %}
          <div class="block">No findings recorded.</div>
        {% endif %}
        {% if conditions %}
          <h2>Conditions</h2>
          <div class="block">{{ conditions }}</div>
        {% endif %}
        <h2>Overall Determination</h2>
        <div class="block">{{ outcome }} · Weighted score {{ weighted_overall }}</div>
        <h2>Attestor Identity</h2>
        <div class="block">
          {% if attestor_email %}
            <p>{{ attestor_name }} &lt;{{ attestor_email }}&gt;</p>
          {% else %}
            <p>{{ attestor_name }}</p>
          {% endif %}
          <p>Verification level {{ verification_level }}</p>
          {% if credentials %}
            <p>Credentials:</p>
            <ul>
            {% for credential in credentials %}
              <li>{{ credential }}</li>
            {% endfor %}
            </ul>
          {% endif %}
        </div>
        {% if supplementary_notes %}
          <h2>Supplementary Notes</h2>
          <div class="block">{{ supplementary_notes }}</div>
        {% endif %}
        <p class="muted">Issued at {{ issued_at }}</p>
      </body>
    </html>
    """
)


def _attestation_report_key(attestation_id: UUID | str) -> str:
    """Return the deterministic S3 key for an Attestation report PDF."""
    return f"attestation-reports/{attestation_id}/report.pdf"


def _build_report_html(context: dict[str, Any]) -> str:
    """Render one attestation report HTML document from context data."""
    return REPORT_TEMPLATE.render(**context)


async def _report_attestor_identity(
    db: Any,
    *,
    attestation: Attestation,
) -> dict[str, Any]:
    """Resolve the attestor-identity block for the report PDF.

    Reports present the organization's name and snapshotted verification level
    with no email (organizations carry no billing email, and the report is a
    shared document) and no individual credentials — the report never names the
    reviewing member.
    """
    org = await db.scalar(
        select(Organization).where(Organization.id == attestation.attestor_org_id)
    )
    level = await db.scalar(
        select(OrgAttestorProfile.verification_level).where(
            OrgAttestorProfile.org_id == attestation.attestor_org_id
        )
    )
    return {
        "name": org.name if org is not None else "Attestor",
        "email": None,
        "verification_level": level if level is not None else 1,
        "credentials": [],
    }


async def _build_report_context(attestation_id: str) -> dict[str, Any]:
    """Load one submitted attestation and assemble the report-render context."""
    parsed_attestation_id = UUID(attestation_id)
    requestor = aliased(User)

    async with async_session_factory() as db:
        row = await db.execute(
            select(Attestation, requestor)
            .join(requestor, requestor.id == Attestation.requestor_id)
            .where(
                Attestation.id == parsed_attestation_id,
                Attestation.status.in_(("report_submitted", "released", "closed")),
            )
        )
        report_row = row.one_or_none()
        if report_row is None:
            raise ValueError("Attestation report not found.")
        attestation, requestor_user = report_row
        if (
            attestation.summary is None
            or attestation.scope is None
            or attestation.outcome is None
            or attestation.issued_at is None
        ):
            raise ValueError("Attestation report is incomplete.")

        attestor_identity = await _report_attestor_identity(
            db,
            attestation=attestation,
        )

        rubric_version = attestation.rubric_version or rubrics.RUBRIC_VERSION
        dimension_rows = (
            await db.execute(
                select(AttestationRubricDimension, AttestationRubricScore)
                .join(
                    AttestationRubricScore,
                    AttestationRubricScore.dimension_id
                    == AttestationRubricDimension.id,
                )
                .where(
                    AttestationRubricScore.attestation_id == attestation.id,
                    AttestationRubricDimension.review_type == attestation.review_type,
                    AttestationRubricDimension.version == rubric_version,
                )
                .order_by(AttestationRubricDimension.display_order)
            )
        ).all()
        methodology = await db.scalar(
            select(AttestationRubricMethodology.text_body).where(
                AttestationRubricMethodology.review_type == attestation.review_type,
                AttestationRubricMethodology.version == rubric_version,
            )
        )
        findings = (
            (
                await db.execute(
                    select(AttestationAnnotation)
                    .where(AttestationAnnotation.attestation_id == attestation.id)
                    .order_by(AttestationAnnotation.created_at)
                )
            )
            .scalars()
            .all()
        )
    score_map = {
        dimension.key: score.score
        for dimension, score in dimension_rows
        if score.score is not None
    }
    weighted_overall = rubrics.weighted_overall(
        score_map,
        attestation.review_type or "",
    )
    supplementary_notes = None
    if attestation.evidence_references:
        supplementary_notes = str(attestation.evidence_references)

    return {
        "attestation_id": str(attestation.id),
        "visibility_label": (
            "pending acceptance"
            if attestation.status == "report_submitted"
            else attestation.status.replace("_", " ")
        ),
        "outcome": attestation.outcome,
        "target_type": attestation.target_type,
        "target_id": str(attestation.target_id),
        "requestor_name": requestor_user.display_name,
        "requestor_email": requestor_user.email,
        "attestor_name": attestor_identity["name"],
        "attestor_email": attestor_identity["email"],
        "verification_level": attestor_identity["verification_level"],
        "credentials": attestor_identity["credentials"],
        "summary": attestation.summary,
        "scope": attestation.scope,
        "methodology": methodology or "",
        "dimensions": [
            {
                "label": dimension.label,
                "weight": f"{Decimal(dimension.weight):.3f}",
                "score": score.score,
                "comment": score.comment or "",
            }
            for dimension, score in dimension_rows
        ],
        "weighted_overall": f"{weighted_overall:.2f}",
        "findings": [
            {
                "annotation_type": finding.annotation_type.replace("_", " "),
                "location_label": finding.location_label,
                "quoted_excerpt": finding.quoted_excerpt,
                "comment": finding.comment,
            }
            for finding in findings
        ],
        "conditions": attestation.conditions,
        "supplementary_notes": supplementary_notes,
        "issued_at": attestation.issued_at.isoformat(),
    }


async def _render_attestation_report_pdf(attestation_id: str) -> tuple[str, bytes]:
    """Render an Attestation report PDF and return its S3 key plus bytes."""
    # Call-time import — see the note in `invoicing/render.py`. WeasyPrint's
    # native dependencies must not gate importing this module.
    from weasyprint import HTML  # type: ignore[import-untyped]

    context = await _build_report_context(attestation_id)
    html = _build_report_html(context)
    pdf_bytes = HTML(string=html).write_pdf()
    return _attestation_report_key(context["attestation_id"]), pdf_bytes


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
