"""Service logic for authenticated account settings."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.security import generate_opaque_token, hash_token, verify_password
from app.integrations import s3
from app.modules.auth import service as auth_service
from app.modules.auth.models import KycDocument, User
from app.modules.settings.schemas import (
    KycStatusResponse,
    KycUploadUrlResponse,
    SessionResponse,
    SessionsResponse,
)
from app.workers.tasks.notifications import send_email_change_verification

ALLOWED_KYC_MIME_TYPES = {"image/jpeg", "image/png", "application/pdf"}
KYC_MAX_FILE_SIZE = 10 * 1024 * 1024
KYC_UPLOAD_URL_TTL_SECONDS = 900
EMAIL_CHANGE_PREFIX = "ec_"
EMAIL_CHANGE_TTL_SECONDS = 86_400


def _email_change_key(token: str) -> str:
    """Build the Redis lookup key for a pending account email change."""
    return f"email_change:{hash_token(token)}"


def _redis_text(value: object) -> str:
    """Normalize Redis bytes/strings to text."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _extension_for_mime(mime_type: str) -> str:
    """Return a stable filename extension for supported KYC MIME types."""
    return {
        "image/jpeg": "jpg",
        "image/png": "png",
        "application/pdf": "pdf",
    }[mime_type]


async def request_kyc_upload_url(
    db: AsyncSession,
    user: User,
    doc_type: str,
    mime_type: str,
    file_size: int,
) -> KycUploadUrlResponse:
    """Create a KYC document record and presigned upload URL."""
    if mime_type not in ALLOWED_KYC_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported KYC document type.",
        )
    if file_size > KYC_MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="KYC document exceeds the 10MB limit.",
        )

    settings = get_settings()
    key = f"kyc/{user.id}/{uuid4()}.{_extension_for_mime(mime_type)}"
    document = KycDocument(
        user_id=user.id,
        doc_type=doc_type,
        s3_key=key,
        mime_type=mime_type,
        file_size=file_size,
    )
    db.add(document)
    upload_url = s3.storage.presigned_put_url(
        bucket=settings.s3_artifacts_bucket,
        key=key,
        mime_type=mime_type,
        expires_in=KYC_UPLOAD_URL_TTL_SECONDS,
    )
    await db.commit()
    return KycUploadUrlResponse(
        upload_url=upload_url,
        s3_key=key,
        max_size=KYC_MAX_FILE_SIZE,
        expires_in=KYC_UPLOAD_URL_TTL_SECONDS,
    )


async def confirm_kyc_upload(
    db: AsyncSession,
    user: User,
    s3_key: str,
) -> KycStatusResponse:
    """Submit a previously requested KYC upload for review."""
    document = await db.scalar(
        select(KycDocument).where(
            KycDocument.user_id == user.id,
            KycDocument.s3_key == s3_key,
        )
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC document not found.",
        )

    settings = get_settings()
    if not s3.storage.object_exists(settings.s3_artifacts_bucket, s3_key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="KYC document has not been uploaded.",
        )

    user.kyc_status = "pending"
    document.status = "pending"
    await write_audit(
        db=db,
        actor_id=user.id,
        action="kyc_status_change",
        target_type="user",
        target_id=user.id,
        metadata={"status": "pending", "s3_key": s3_key},
    )
    await db.commit()
    return await get_kyc_status(db=db, user=user)


async def get_kyc_status(db: AsyncSession, user: User) -> KycStatusResponse:
    """Return the current user's KYC status and document metadata."""
    documents = (
        await db.execute(
            select(KycDocument)
            .where(KycDocument.user_id == user.id)
            .order_by(desc(KycDocument.created_at))
        )
    ).scalars().all()
    return KycStatusResponse(kyc_status=user.kyc_status, documents=list(documents))


async def list_sessions(
    redis: Redis,
    user: User,
    current_refresh_token: str | None,
) -> SessionsResponse:
    """List active refresh-token sessions for the authenticated user."""
    sessions = await auth_service.list_refresh_sessions(
        redis=redis,
        user=user,
        current_token=current_refresh_token,
    )
    return SessionsResponse(
        sessions=[SessionResponse.model_validate(session) for session in sessions]
    )


async def revoke_session(
    db: AsyncSession,
    redis: Redis,
    user: User,
    session_id: str,
    current_refresh_token: str | None,
) -> bool:
    """Revoke a single refresh-token session owned by the authenticated user."""
    revoked = await auth_service.revoke_refresh_session(
        redis=redis,
        user=user,
        session_id=session_id,
    )
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )

    current = (
        auth_service.refresh_session_id(current_refresh_token) == session_id
        if current_refresh_token
        else False
    )
    await write_audit(
        db=db,
        actor_id=user.id,
        action="session_revoked",
        target_type="session",
        target_id=user.id,
        metadata={"session_id": session_id, "current": current},
    )
    await db.commit()
    return current


async def revoke_other_sessions(
    db: AsyncSession,
    redis: Redis,
    user: User,
    current_refresh_token: str | None,
) -> int:
    """Revoke every user session except the current browser session."""
    revoked = await auth_service.revoke_other_refresh_sessions(
        redis=redis,
        user=user,
        current_token=current_refresh_token,
    )
    await write_audit(
        db=db,
        actor_id=user.id,
        action="sessions_revoked",
        target_type="user",
        target_id=user.id,
        metadata={"revoked_count": revoked, "scope": "others"},
    )
    await db.commit()
    return revoked


async def request_email_change(
    db: AsyncSession,
    redis: Redis,
    user: User,
    new_email: str,
    totp_code: str | None,
) -> None:
    """Create a new-email verification token after TOTP confirmation."""
    normalized_email = auth_service.normalize_email(new_email)
    if normalized_email == user.email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already belongs to this account.",
        )
    existing = await db.scalar(select(User).where(User.email == normalized_email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already in use.",
        )

    await auth_service.verify_totp_for_sensitive_action(
        db=db,
        redis=redis,
        user=user,
        code=totp_code,
    )

    token = f"{EMAIL_CHANGE_PREFIX}{generate_opaque_token()}"
    await redis.setex(
        _email_change_key(token),
        EMAIL_CHANGE_TTL_SECONDS,
        json.dumps({"user_id": str(user.id), "new_email": normalized_email}),
    )
    send_email_change_verification.delay(normalized_email, token)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="email_change_requested",
        target_type="user",
        target_id=user.id,
        metadata={"new_email": normalized_email},
    )
    await db.commit()


async def confirm_email_change(
    db: AsyncSession,
    redis: Redis,
    token: str,
) -> UUID:
    """Confirm a new account email address and revoke all sessions."""
    if not token.startswith(EMAIL_CHANGE_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email-change token.",
        )

    key = _email_change_key(token)
    raw_record = await redis.get(key)
    if raw_record is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Email-change token expired or already used.",
        )

    record = json.loads(_redis_text(raw_record))
    user_id = UUID(str(record["user_id"]))
    new_email = str(record["new_email"])
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None or user.deactivated_at is not None:
        await redis.delete(key)
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Email-change token expired or already used.",
        )

    if await db.scalar(select(User).where(User.email == new_email)) is not None:
        await redis.delete(key)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already in use.",
        )

    user.email = new_email
    user.email_verified = True
    await auth_service.revoke_all_user_sessions(redis=redis, user=user)
    await redis.delete(key)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="email_changed",
        target_type="user",
        target_id=user.id,
        metadata={"new_email": new_email},
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already in use.",
        ) from exc
    return user.id


async def deactivate_account(
    db: AsyncSession,
    redis: Redis,
    user: User,
    password: str,
    totp_code: str | None,
) -> None:
    """Deactivate the authenticated account and revoke all browser sessions."""
    if user.password_hash is None or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password.",
        )

    if user.totp_enabled:
        await auth_service.verify_totp_for_sensitive_action(
            db=db,
            redis=redis,
            user=user,
            code=totp_code,
        )

    user.deactivated_at = datetime.now(UTC)
    await auth_service.revoke_all_user_sessions(redis=redis, user=user)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="account_deactivated",
        target_type="user",
        target_id=user.id,
    )
    await db.commit()
