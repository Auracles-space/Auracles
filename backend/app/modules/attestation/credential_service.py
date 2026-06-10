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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.attestation.models import AttestationUploadSession, Credential
from app.modules.attestation.schemas import (
    CredentialCreateRequest,
    CredentialEvidenceUploadCreateRequest,
    CredentialEvidenceUploadSessionResponse,
    CredentialUpdateRequest,
)
from app.modules.auth.models import User
from app.workers.tasks.attestation_upload_scan import scan_attestation_upload

CREDENTIAL_EVIDENCE_UPLOAD_TTL_SECONDS = 300
CREDENTIAL_EVIDENCE_MAX_BYTES = 10 * 1024 * 1024


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
        if payload.title is not None:
            credential.title = payload.title
        if payload.issuer is not None:
            credential.issuer = payload.issuer
        if payload.issued_date is not None:
            credential.issued_date = payload.issued_date
        if "expires_date" in payload.model_fields_set:
            credential.expires_date = payload.expires_date
        if payload.evidence_file_keys is not None:
            await _consume_credential_evidence_sessions(
                db=db,
                credential_id=credential.id,
                user_id=user_id,
                file_keys=payload.evidence_file_keys,
                now=datetime.now(UTC),
            )
            credential.evidence_file_keys = payload.evidence_file_keys
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
    pending_scan_ids = [
        row.id for row in rows if row.scan_status == "pending_scan"
    ]
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
