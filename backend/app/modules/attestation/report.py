"""Attestation report submission and report-evidence upload orchestration.

The request path keeps expensive PDF rendering out of the HTTP transaction. It
persists structured report fields, consumes private evidence upload sessions,
and then dispatches the Celery renderer after the database commit succeeds.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.attestation import notifications as attestation_notifications
from app.modules.attestation import quality_gate, rubrics
from app.modules.attestation.dependencies import resolve_attestor_actor
from app.modules.attestation.models import (
    Attestation,
    AttestationUploadSession,
)
from app.modules.attestation.schemas import (
    AttestationEvidenceFile,
    AttestationEvidenceFilesResponse,
    AttestationEvidenceUploadCreateRequest,
    AttestationEvidenceUploadSessionResponse,
    AttestationReportSubmitRequest,
)
from app.modules.auth.models import User
from app.modules.financials.models import PlatformConfig
from app.modules.organizations.models import OrgAttestorProfile
from app.shared.business_days import add_business_days
from app.workers.tasks.attestation_pdf import render_attestation_report_pdf
from app.workers.tasks.attestation_upload_scan import scan_attestation_upload

REPORT_EVIDENCE_UPLOAD_TTL_SECONDS = 300
REPORT_EVIDENCE_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_DISPUTE_WINDOW_BUSINESS_DAYS = 5


def attestation_report_key(attestation_id: UUID | str) -> str:
    """Return the deterministic S3 key for an Attestation report PDF."""
    return f"attestation-reports/{attestation_id}/report.pdf"


def _safe_file_name(file_name: str) -> str:
    """Return a path-safe file name segment for Attestation evidence keys."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", file_name.strip()).strip("-")
    return cleaned or "attestation-evidence"


async def create_report_evidence_upload_session(
    *,
    db: AsyncSession,
    attestor: User,
    attestation_id: UUID,
    payload: AttestationEvidenceUploadCreateRequest,
) -> AttestationEvidenceUploadSessionResponse:
    """Create a presigned POST session for assigned-Attestor report evidence."""
    attestor_id = attestor.id
    if payload.size_bytes > REPORT_EVIDENCE_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Attestation report evidence upload is too large.",
        )
    if db.in_transaction():
        await db.rollback()

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=REPORT_EVIDENCE_UPLOAD_TTL_SECONDS)
    key = (
        f"attestations/{attestation_id}/evidence/{attestor_id}/{uuid4()}-"
        f"{_safe_file_name(payload.file_name)}"
    )
    async with db.begin():
        await _load_assigned_attestation_for_update(
            db=db,
            attestation_id=attestation_id,
            user_id=attestor_id,
            allowed_statuses={"in_review", "revision_requested"},
        )
        upload_session = AttestationUploadSession(
            attestation_id=attestation_id,
            user_id=attestor_id,
            purpose="report_evidence",
            s3_key=key,
            content_type=payload.content_type,
            size_limit=REPORT_EVIDENCE_MAX_BYTES,
            scan_status="pending_scan",
            expires_at=expires_at,
        )
        db.add(upload_session)
        await db.flush()
        await db.refresh(upload_session)

    settings = get_settings()
    post = s3.storage.presigned_post(
        settings.s3_artifacts_bucket,
        key,
        payload.content_type,
        REPORT_EVIDENCE_MAX_BYTES,
        REPORT_EVIDENCE_UPLOAD_TTL_SECONDS,
    )
    return AttestationEvidenceUploadSessionResponse(
        id=upload_session.id,
        s3_key=key,
        url=str(post["url"]),
        fields={str(key_): str(value) for key_, value in post["fields"].items()},
        expires_at=expires_at,
        size_limit=REPORT_EVIDENCE_MAX_BYTES,
        scan_status=upload_session.scan_status,
    )


async def submit_report(
    *,
    db: AsyncSession,
    attestor: User,
    attestation_id: UUID,
    payload: AttestationReportSubmitRequest,
) -> Attestation:
    """Persist the assigned Attestor's report and queue PDF rendering."""
    attestor_id = attestor.id
    if db.in_transaction():
        await db.rollback()
    now = datetime.now(UTC)
    report_key = attestation_report_key(attestation_id)

    async with db.begin():
        attestation = await _load_assigned_attestation_for_update(
            db=db,
            attestation_id=attestation_id,
            user_id=attestor_id,
            allowed_statuses={"in_review", "revision_requested"},
        )
        failures = await quality_gate.evaluate_quality_gate(
            db,
            attestation=attestation,
            summary=payload.summary,
            scope=payload.scope,
            conditions=payload.conditions,
            outcome=payload.outcome,
        )
        if failures:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=failures,
            )
        evidence_file_keys = _evidence_file_keys(payload.evidence_references)
        if evidence_file_keys:
            await _consume_report_evidence_sessions(
                db=db,
                attestation_id=attestation.id,
                attestor_id=attestor_id,
                file_keys=evidence_file_keys,
                now=now,
            )
        dispute_window_business_days = await _platform_int_config(
            db,
            key="attestation_dispute_window_business_days",
            default=DEFAULT_DISPUTE_WINDOW_BUSINESS_DAYS,
            minimum=1,
        )
        attestation.status = "report_submitted"
        attestation.outcome = payload.outcome
        attestation.summary = payload.summary
        attestation.scope = payload.scope
        attestation.conditions = payload.conditions
        attestation.evidence_references = payload.evidence_references
        attestation.report_key = report_key
        attestation.issued_at = now
        attestation.dispute_window_ends_at = add_business_days(
            now, dispute_window_business_days
        )
        attestation.rubric_version = rubrics.RUBRIC_VERSION
        if (
            attestation.completion_due_at is not None
            and now > attestation.completion_due_at
        ):
            attestation.submitted_late = True
            org_profile = await db.scalar(
                select(OrgAttestorProfile)
                .where(OrgAttestorProfile.org_id == attestation.attestor_org_id)
                .with_for_update()
            )
            if org_profile is not None:
                org_profile.late_submission_count += 1
            await write_audit(
                db=db,
                actor_id=attestor_id,
                action="attestation_late_submission",
                target_type="attestation",
                target_id=attestation.id,
                metadata={"submitted_late": True},
            )
        await write_audit(
            db=db,
            actor_id=attestor_id,
            action="attestation_report_submitted",
            target_type="attestation",
            target_id=attestation.id,
            metadata={
                "outcome": payload.outcome,
                "evidence_file_count": len(evidence_file_keys),
            },
        )
        await write_audit(
            db=db,
            actor_id=attestor_id,
            action="attestation_published",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"report_key": report_key, "visibility": "pending_acceptance"},
        )
        await write_audit(
            db=db,
            actor_id=attestor_id,
            action="attestation_outcome_recorded",
            target_type="attestation",
            target_id=attestation.id,
            metadata={
                "outcome": payload.outcome,
                "target_type": attestation.target_type,
                "target_id": str(attestation.target_id),
                "attestor_id": str(attestor_id),
                "requestor_id": str(attestation.requestor_id),
            },
        )
        await db.flush()

    render_attestation_report_pdf.delay(str(attestation_id))
    attestation_notifications.notify_report_submitted(attestation)
    await db.refresh(attestation)
    return attestation


def _evidence_file_keys(evidence_references: dict[str, Any]) -> list[str]:
    """Extract uploaded evidence S3 keys from the structured evidence JSON."""
    raw_file_keys = evidence_references.get("file_keys", [])
    if raw_file_keys is None:
        return []
    if not isinstance(raw_file_keys, list) or not all(
        isinstance(item, str) for item in raw_file_keys
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="evidence_references.file_keys must be a list of strings.",
        )
    return raw_file_keys


async def _consume_report_evidence_sessions(
    *,
    db: AsyncSession,
    attestation_id: UUID,
    attestor_id: UUID,
    file_keys: list[str],
    now: datetime,
) -> None:
    """Validate and consume report evidence upload sessions before publishing."""
    if len(set(file_keys)) != len(file_keys):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Attestation evidence keys must be unique.",
        )

    rows = (
        (
            await db.execute(
                select(AttestationUploadSession)
                .where(
                    AttestationUploadSession.attestation_id == attestation_id,
                    AttestationUploadSession.user_id == attestor_id,
                    AttestationUploadSession.purpose == "report_evidence",
                    AttestationUploadSession.s3_key.in_(file_keys),
                    AttestationUploadSession.consumed_at.is_(None),
                    AttestationUploadSession.expires_at > now,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    by_key = {row.s3_key: row for row in rows}
    if set(by_key) != set(file_keys):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Report contains invalid or expired evidence upload keys.",
        )
    pending_scan_ids = [row.id for row in rows if row.scan_status == "pending_scan"]
    for upload_session_id in pending_scan_ids:
        scan_attestation_upload.delay(str(upload_session_id))
    if pending_scan_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Report evidence is still scanning. Try again shortly.",
        )
    unsafe_statuses = {
        row.scan_status for row in rows if row.scan_status in {"infected", "error"}
    }
    if unsafe_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Report evidence upload did not pass scanning.",
        )
    for row in rows:
        row.consumed_at = now


async def _load_assigned_attestation_for_update(
    *,
    db: AsyncSession,
    attestation_id: UUID,
    user_id: UUID,
    allowed_statuses: set[str],
) -> Attestation:
    """Load a locked Attestation writable by its reviewing member in a state.

    The reviewing member (or, during coexistence, the legacy assigned attestor)
    holds write access; unrelated callers are hidden the attestation (404).
    """
    attestation = await db.scalar(
        select(Attestation).where(Attestation.id == attestation_id).with_for_update()
    )
    if attestation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    await resolve_attestor_actor(db, attestation=attestation, user_id=user_id)
    if attestation.status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation is not ready for report submission.",
        )
    return attestation


async def _platform_int_config(
    db: AsyncSession,
    *,
    key: str,
    default: int,
    minimum: int,
) -> int:
    """Read a positive integer platform configuration value."""
    configured = await db.scalar(
        select(PlatformConfig.value).where(PlatformConfig.key == key)
    )
    if configured is None:
        return default
    try:
        parsed = int(configured)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{key} configuration is invalid.",
        ) from exc
    if parsed < minimum:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{key} configuration is invalid.",
        )
    return parsed


# Presigned evidence links live as long as artifact links (15 minutes).
EVIDENCE_LINK_TTL_SECONDS = 900


def _evidence_display_name(s3_key: str) -> str:
    """Recover the uploaded file name from ``.../{uuid}-{safe_file_name}``."""
    last_segment = s3_key.rsplit("/", 1)[-1]
    prefix, name = last_segment[:36], last_segment[37:]
    # The prefix is a hyphenated UUID, so split by length rather than on the
    # first hyphen; a key without that shape still shows its last segment.
    try:
        UUID(prefix)
    except ValueError:
        return last_segment
    return name if last_segment[36:37] == "-" and name else last_segment


async def list_report_evidence_files(
    db: AsyncSession,
    *,
    user: User,
    attestation_id: UUID,
) -> AttestationEvidenceFilesResponse:
    """Return the report's evidence files with audited presigned download links.

    Visible to whoever may read the attestation (requestor, attestor org,
    admin); everyone else gets 404. Links are issued only for files that
    scanned clean, and each issue is written to the audit log.

    Args:
        db: Async database session.
        user: Authenticated caller.
        attestation_id: Attestation whose report evidence is requested.

    Returns:
        The evidence files in the order the attestor attached them.

    Raises:
        HTTPException(404): The attestation is not visible to the caller.
    """
    from app.modules.attestation.matching_service import get_attestation_for_user

    user_id = user.id
    attestation = await get_attestation_for_user(
        db, attestation_id=attestation_id, user=user
    )
    file_keys = _evidence_file_keys(attestation.evidence_references or {})
    if not file_keys:
        return AttestationEvidenceFilesResponse(
            files=[], expires_in_seconds=EVIDENCE_LINK_TTL_SECONDS
        )
    sessions = {
        row.s3_key: row
        for row in (
            await db.execute(
                select(AttestationUploadSession).where(
                    AttestationUploadSession.attestation_id == attestation.id,
                    AttestationUploadSession.purpose == "report_evidence",
                    AttestationUploadSession.s3_key.in_(file_keys),
                )
            )
        ).scalars()
    }
    settings = get_settings()
    files: list[AttestationEvidenceFile] = []
    for key in file_keys:
        upload = sessions.get(key)
        if upload is None:
            continue
        name = _evidence_display_name(key)
        url = (
            s3.storage.presigned_get(
                settings.s3_artifacts_bucket,
                key,
                EVIDENCE_LINK_TTL_SECONDS,
                download_name=name,
            )
            if upload.scan_status == "clean"
            else None
        )
        files.append(
            AttestationEvidenceFile(
                file_name=name, scan_status=upload.scan_status, download_url=url
            )
        )
    linked = sum(1 for item in files if item.download_url)
    if linked:
        if db.in_transaction():
            await db.rollback()
        async with db.begin():
            await write_audit(
                db=db,
                actor_id=user_id,
                action="attestation_evidence_links_issued",
                target_type="attestation",
                target_id=attestation_id,
                metadata={"links_issued": linked},
            )
    return AttestationEvidenceFilesResponse(
        files=files, expires_in_seconds=EVIDENCE_LINK_TTL_SECONDS
    )
