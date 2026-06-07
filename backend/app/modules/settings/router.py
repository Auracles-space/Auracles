"""FastAPI router for authenticated settings endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.settings import service
from app.modules.settings.schemas import (
    KycStatusResponse,
    KycSubmitRequest,
    KycUploadUrlRequest,
    KycUploadUrlResponse,
)

router = APIRouter(prefix="/settings", tags=["Settings"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("/kyc/upload-url", response_model=KycUploadUrlResponse)
async def request_kyc_upload_url(
    payload: KycUploadUrlRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> KycUploadUrlResponse:
    """Create a presigned KYC upload URL for the authenticated user."""
    return await service.request_kyc_upload_url(
        db=db,
        user=current_user,
        doc_type=payload.doc_type,
        mime_type=payload.mime_type,
        file_size=payload.file_size,
    )


@router.post("/kyc/submit", response_model=KycStatusResponse)
async def submit_kyc_upload(
    payload: KycSubmitRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> KycStatusResponse:
    """Submit a previously uploaded KYC document for review."""
    return await service.confirm_kyc_upload(
        db=db,
        user=current_user,
        s3_key=payload.s3_key,
    )


@router.get("/kyc", response_model=KycStatusResponse)
async def get_kyc_status(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> KycStatusResponse:
    """Return the authenticated user's KYC status."""
    return await service.get_kyc_status(db=db, user=current_user)
