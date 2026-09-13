"""Credential service logic.

Credentials are user-owned professional claims that can later be selected as
Attestation targets. This slice keeps ownership enforcement in one service
module so router handlers stay thin.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.admin.notifications import notify_admins_review_pending
from app.modules.attestation.models import AttestationUploadSession, Credential
from app.modules.attestation.schemas import (
    CredentialCreateRequest,
    CredentialEvidenceUploadCreateRequest,
    CredentialEvidenceUploadSessionResponse,
    CredentialUpdateRequest,
)
from app.modules.auth.models import User
from app.workers.tasks.attestation_upload_scan import scan_attestation_upload
from app.workers.tasks.project_notifications import dispatch_project_notification

CREDENTIAL_EVIDENCE_UPLOAD_TTL_SECONDS = 300
CREDENTIAL_EVIDENCE_MAX_BYTES = 10 * 1024 * 1024

_SUBMITTABLE_STATUSES = {"unverified", "rejected"}


def _safe_file_name(file_name: str) -> str:
    """Return a path-safe file name segment for Credential evidence keys."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", file_name.strip()).strip("-")
    return cleaned or "credential-evidence"


async def create_credential(
    db: AsyncSession,
    user: User,
    payload: CredentialCreateRequest,
) -> Credential:
    """Create a professional Credential owned by the authenticated user."""
    user_id = user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        credential = Credential(
            user_id=user_id,
            title=payload.title,
            issuer=payload.issuer,
            issued_date=payload.issued_date,
            expires_date=payload.expires_date,
        )
        db.add(credential)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=user_id,
            action="credential_created",
            target_type="credential",
            target_id=credential.id,
            metadata={"title": credential.title},
        )
        await db.refresh(credential)
    return credential


async def submit_credential(
    db: AsyncSession,
    user: User,
    credential_id: UUID,
) -> Credential:
    """Submit an owned Credential for manual Admin verification.

    Transitions ``unverified``/``rejected`` to ``pending``. Requires at least
    one piece of reviewable evidence (an uploaded file, a verification URL, or a
    reference number) so an Admin has something to check.

    Args:
        db: Async database session.
        user: Authenticated owner of the Credential.
        credential_id: UUID of the Credential to submit.

    Returns:
        The updated Credential in ``pending`` state.

    Raises:
        HTTPException(404): Credential missing or not owned by the user.
        HTTPException(422): Invalid state transition or no reviewable evidence.
    """
    user_id = user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        credential = await _load_owned_credential_for_update(
            db=db, user_id=user_id, credential_id=credential_id
        )
        if credential.verification_status not in _SUBMITTABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Credential cannot be submitted from its current state.",
            )
        has_evidence = bool(
            credential.evidence_file_keys
            or credential.verification_url
            or credential.reference_number
        )
        if not has_evidence:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Attach evidence, a verification URL, or a reference number "
                "before submitting.",
            )
        credential.verification_status = "pending"
        credential.submitted_at = datetime.now(UTC)
        credential.rejection_reason = None
        await write_audit(
            db=db,
            actor_id=user_id,
            action="credential_submitted",
            target_type="credential",
            target_id=credential.id,
            metadata={"title": credential.title},
        )
        await db.flush()
        await db.refresh(credential)
    notify_admins_review_pending(
        domain="credential",
        target_id=credential.id,
        body=f"Credential “{credential.title}” was submitted for verification.",
        link="/admin/credentials",
    )
    return credential


async def list_credentials(
    db: AsyncSession,
    user: User,
) -> list[Credential]:
    """Return Credentials owned by the authenticated user."""
    result = await db.execute(
        select(Credential)
        .where(Credential.user_id == user.id)
        .order_by(Credential.created_at.desc())
    )
    return list(result.scalars().all())


async def update_credential(
    db: AsyncSession,
    user: User,
    credential_id: UUID,
    payload: CredentialUpdateRequest,
) -> Credential:
    """Update a Credential when it belongs to the authenticated user."""
    user_id = user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        credential = await _load_owned_credential_for_update(
            db=db,
            user_id=user_id,
            credential_id=credential_id,
        )
        material_changed = False
        if payload.title is not None and payload.title != credential.title:
            credential.title = payload.title
            material_changed = True
        if payload.issuer is not None and payload.issuer != credential.issuer:
            credential.issuer = payload.issuer
            material_changed = True
        if (
            payload.issued_date is not None
            and payload.issued_date != credential.issued_date
        ):
            credential.issued_date = payload.issued_date
            material_changed = True
        if "expires_date" in payload.model_fields_set:
            credential.expires_date = payload.expires_date
        if payload.credential_type is not None:
            credential.credential_type = payload.credential_type
        if payload.verification_url is not None:
            credential.verification_url = payload.verification_url
        if (
            payload.reference_number is not None
            and payload.reference_number != credential.reference_number
        ):
            credential.reference_number = payload.reference_number
            material_changed = True
        if payload.issuer_type is not None:
            credential.issuer_type = payload.issuer_type
        if payload.evidence_file_keys is not None:
            await _consume_credential_evidence_sessions(
                db=db,
                credential_id=credential.id,
                user_id=user_id,
                file_keys=payload.evidence_file_keys,
                now=datetime.now(UTC),
            )
            credential.evidence_file_keys = payload.evidence_file_keys
        if material_changed and credential.verification_status in {
            "pending",
            "verified",
        }:
            credential.verification_status = "unverified"
            credential.submitted_at = None
            credential.verified_at = None
            credential.reviewed_by = None
            credential.rejection_reason = None
            await write_audit(
                db=db,
                actor_id=user_id,
                action="credential_verification_reset",
                target_type="credential",
                target_id=credential.id,
                metadata={"title": credential.title},
            )
        await db.flush()
        await db.refresh(credential)
    return credential


async def delete_credential(
    db: AsyncSession,
    user: User,
    credential_id: UUID,
) -> None:
    """Delete a Credential owned by the authenticated user."""
    user_id = user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        credential = await _load_owned_credential_for_update(
            db=db,
            user_id=user_id,
            credential_id=credential_id,
        )
        await db.delete(credential)
        await write_audit(
            db=db,
            actor_id=user_id,
            action="credential_deleted",
            target_type="credential",
            target_id=credential_id,
            metadata={"title": credential.title},
        )


async def create_evidence_upload_session(
    db: AsyncSession,
    user: User,
    credential_id: UUID,
    payload: CredentialEvidenceUploadCreateRequest,
) -> CredentialEvidenceUploadSessionResponse:
    """Create a presigned POST session for Credential evidence upload."""
    user_id = user.id
    if payload.size_bytes > CREDENTIAL_EVIDENCE_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Credential evidence upload is too large.",
        )
    if db.in_transaction():
        await db.rollback()

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=CREDENTIAL_EVIDENCE_UPLOAD_TTL_SECONDS)
    key = (
        f"credentials/{credential_id}/{user_id}/{uuid4()}-"
        f"{_safe_file_name(payload.file_name)}"
    )
    async with db.begin():
        await _load_owned_credential_for_update(
            db=db,
            user_id=user_id,
            credential_id=credential_id,
        )
        upload_session = AttestationUploadSession(
            credential_id=credential_id,
            user_id=user_id,
            purpose="credential_evidence",
            s3_key=key,
            content_type=payload.content_type,
            size_limit=CREDENTIAL_EVIDENCE_MAX_BYTES,
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
        CREDENTIAL_EVIDENCE_MAX_BYTES,
        CREDENTIAL_EVIDENCE_UPLOAD_TTL_SECONDS,
    )
    return CredentialEvidenceUploadSessionResponse(
        id=upload_session.id,
        s3_key=key,
        url=str(post["url"]),
        fields={str(key_): str(value) for key_, value in post["fields"].items()},
        expires_at=expires_at,
        size_limit=CREDENTIAL_EVIDENCE_MAX_BYTES,
        scan_status=upload_session.scan_status,
    )


async def _consume_credential_evidence_sessions(
    db: AsyncSession,
    credential_id: UUID,
    user_id: UUID,
    file_keys: list[str],
    now: datetime,
) -> None:
    """Validate and consume upload sessions before attaching evidence keys."""
    if len(set(file_keys)) != len(file_keys):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Credential evidence keys must be unique.",
        )

    rows = (
        (
            await db.execute(
                select(AttestationUploadSession)
                .where(
                    AttestationUploadSession.credential_id == credential_id,
                    AttestationUploadSession.user_id == user_id,
                    AttestationUploadSession.purpose == "credential_evidence",
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
            detail="Credential contains invalid or expired evidence upload keys.",
        )
    pending_scan_ids = [row.id for row in rows if row.scan_status == "pending_scan"]
    for upload_session_id in pending_scan_ids:
        scan_attestation_upload.delay(str(upload_session_id))
    if pending_scan_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Credential evidence is still scanning. Try again shortly.",
        )
    unsafe_statuses = {
        row.scan_status for row in rows if row.scan_status in {"infected", "error"}
    }
    if unsafe_statuses:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Credential evidence upload did not pass scanning.",
        )
    for row in rows:
        row.consumed_at = now


CREDENTIAL_EVIDENCE_DOWNLOAD_TTL_SECONDS = 300


async def generate_evidence_download_url(
    db: AsyncSession,
    requester_id: UUID,
    credential_id: UUID,
    key: str,
    is_admin: bool,
) -> str:
    """Return a short-TTL presigned GET URL for one credential evidence file.

    Owners may download their own credential's evidence in any state; admins may
    download any credential's evidence. The key must belong to the credential.
    Writes a ``credential_evidence_download`` audit row. The presigned URL is
    never logged.

    Raises:
        HTTPException(404): Credential not found, or key not on the credential.
        HTTPException(403): Requester is neither the owner nor an admin.
    """
    credential = await db.scalar(
        select(Credential).where(Credential.id == credential_id)
    )
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found."
        )
    if not is_admin and credential.user_id != requester_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not permitted to access this credential's evidence.",
        )
    if key not in credential.evidence_file_keys:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence file not found for this credential.",
        )
    credential_pk = credential.id
    settings = get_settings()
    url = s3.storage.presigned_get(
        settings.s3_artifacts_bucket,
        key,
        CREDENTIAL_EVIDENCE_DOWNLOAD_TTL_SECONDS,
    )
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await write_audit(
            db=db,
            actor_id=requester_id,
            action="credential_evidence_download",
            target_type="credential",
            target_id=credential_pk,
            metadata={"key_suffix": key.rsplit("/", 1)[-1], "is_admin": is_admin},
        )
    return url


async def _load_owned_credential_for_update(
    db: AsyncSession,
    user_id: UUID,
    credential_id: UUID,
) -> Credential:
    """Load an owned Credential with a row lock or raise 404."""
    credential = await db.scalar(
        select(Credential)
        .where(Credential.id == credential_id, Credential.user_id == user_id)
        .with_for_update()
    )
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found.",
        )
    return credential


def _notify_credential_decision(
    *, user_id: UUID, credential: Credential, verified: bool
) -> None:
    """Queue a durable notification telling the owner of a review decision."""
    notification_type = "credential_verified" if verified else "credential_rejected"
    title = "Credential verified" if verified else "Credential needs attention"
    body = (
        "Your credential has been verified."
        if verified
        else "Your credential was not verified. Review the feedback and resubmit."
    )
    try:
        dispatch_project_notification.delay(
            user_id=str(user_id),
            notification_type=notification_type,
            title=title,
            body=body,
            payload={
                "credential_id": str(credential.id),
                "status": credential.verification_status,
            },
            link="/settings/credentials",
            dedupe_key=f"{notification_type}:{credential.id}",
        )
    except Exception as exc:  # pragma: no cover - dispatch best-effort
        logger.bind(
            module="attestation",
            action="notify_credential_decision",
            user_id=user_id,
            credential_id=credential.id,
        ).error("notification_dispatch_failed", error=str(exc))


async def list_credentials_for_review(
    db: AsyncSession, verification_status: str | None = "pending"
) -> list[Credential]:
    """Return credentials filtered by verification status for admin review.

    Args:
        db: Async database session.
        verification_status: Status to filter by, or ``None`` for all
            credentials regardless of status.

    Returns:
        Credentials matching the filter, most recently submitted first.
    """
    stmt = select(Credential).order_by(Credential.submitted_at.desc().nullslast())
    if verification_status is not None:
        stmt = stmt.where(Credential.verification_status == verification_status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _load_credential_for_review(
    db: AsyncSession, credential_id: UUID
) -> Credential:
    """Load any credential by id with a row lock or raise 404 (admin scope)."""
    credential = await db.scalar(
        select(Credential).where(Credential.id == credential_id).with_for_update()
    )
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found."
        )
    return credential


async def verify_credential(
    db: AsyncSession,
    admin_id: UUID,
    credential_id: UUID,
) -> Credential:
    """Mark a pending Credential verified (Admin action).

    Verification feeds attestor eligibility, so it is a trust decision rather
    than a routine edit: the route requires an open step-up window
    (``require_step_up``), gated like the admin suspensions.

    Args:
        db: Async database session.
        admin_id: UUID of the acting admin.
        credential_id: UUID of the credential under review.

    Returns:
        The verified Credential.

    Raises:
        HTTPException(403): Admin is reviewing their own credential.
        HTTPException(404): Credential not found.
        HTTPException(422): Credential is not pending.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        credential = await _load_credential_for_review(db, credential_id)
        if credential.user_id == admin_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admins cannot review their own credentials.",
            )
        if credential.verification_status != "pending":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only pending credentials can be verified.",
            )
        credential.verification_status = "verified"
        credential.verified_at = datetime.now(UTC)
        credential.reviewed_by = admin_id
        credential.rejection_reason = None
        owner_id = credential.user_id
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="credential_verified",
            target_type="credential",
            target_id=credential.id,
            metadata={"owner_id": str(owner_id)},
        )
        await db.flush()
        await db.refresh(credential)
    _notify_credential_decision(user_id=owner_id, credential=credential, verified=True)
    return credential


async def reject_credential(
    db: AsyncSession,
    admin_id: UUID,
    credential_id: UUID,
    reason: str,
) -> Credential:
    """Reject a pending Credential with a reason (Admin action).

    Gated by an open step-up window on the route, matching
    :func:`verify_credential`: a rejection blocks an attestor's eligibility and
    must not be reachable from a stolen admin session alone.

    Args:
        db: Async database session.
        admin_id: UUID of the acting admin.
        credential_id: UUID of the credential under review.
        reason: Required non-empty rejection reason.

    Returns:
        The rejected Credential.

    Raises:
        HTTPException(403): Admin is reviewing their own credential.
        HTTPException(404): Credential not found.
        HTTPException(422): Credential is not pending.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        credential = await _load_credential_for_review(db, credential_id)
        if credential.user_id == admin_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admins cannot review their own credentials.",
            )
        if credential.verification_status != "pending":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only pending credentials can be rejected.",
            )
        credential.verification_status = "rejected"
        credential.rejection_reason = reason
        credential.reviewed_by = admin_id
        credential.verified_at = None
        owner_id = credential.user_id
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="credential_rejected",
            target_type="credential",
            target_id=credential.id,
            metadata={"owner_id": str(owner_id), "reason": reason},
        )
        await db.flush()
        await db.refresh(credential)
    _notify_credential_decision(user_id=owner_id, credential=credential, verified=False)
    return credential
