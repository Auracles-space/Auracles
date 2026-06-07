"""Service logic for authenticated account settings."""

from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.auth.models import KycDocument, User
from app.modules.settings.schemas import KycStatusResponse, KycUploadUrlResponse

ALLOWED_KYC_MIME_TYPES = {"image/jpeg", "image/png", "application/pdf"}
KYC_MAX_FILE_SIZE = 10 * 1024 * 1024
KYC_UPLOAD_URL_TTL_SECONDS = 900


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
