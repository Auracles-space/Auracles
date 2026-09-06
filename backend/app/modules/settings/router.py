"""FastAPI router for authenticated settings endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cookies import (
    REFRESH_COOKIE_NAME,
    clear_refresh_cookie,
    clear_session_hint_cookie,
)
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.redis import get_redis
from app.modules.auth.models import User
from app.modules.auth.schemas import RegisterResponse
from app.modules.notifications import preferences as notification_preferences
from app.modules.notifications.schemas import (
    NotificationPreferencesResponse,
    NotificationPreferencesUpdateRequest,
)
from app.modules.settings import service
from app.modules.settings.schemas import (
    EmailChangeConfirmRequest,
    EmailChangeRequest,
    KycDocumentResponse,
    KycDocumentUploadRequest,
    KycDocumentUploadResponse,
    KycStatusResponse,
    KycSyncRequest,
    KycVerificationSessionResponse,
    SessionsResponse,
)

router = APIRouter(prefix="/settings", tags=["Settings"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("/kyc/session", response_model=KycVerificationSessionResponse)
async def start_identity_verification(
    current_user: CurrentUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> KycVerificationSessionResponse:
    """Start a Persona identity-verification session for the current user."""
    return await service.start_identity_verification(
        db=db,
        redis=redis,
        user=current_user,
    )


@router.get("/kyc", response_model=KycStatusResponse)
async def get_kyc_status(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> KycStatusResponse:
    """Return the authenticated user's KYC status."""
    return await service.get_kyc_status(db=db, user=current_user)


@router.post(
    "/kyc/documents",
    response_model=KycDocumentUploadResponse,
    summary="Request an upload target for an identity document",
    description=(
        "Reserves an identity document and returns a presigned S3 POST policy. "
        "Post the file to `upload_url` as multipart form data — every entry in "
        "`fields` first, the file part last — then call the confirm endpoint. "
        "The document is not submitted for review until it is confirmed."
    ),
)
async def request_kyc_document_upload_url(
    payload: KycDocumentUploadRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> KycDocumentUploadResponse:
    """Return a presigned POST target for one identity document."""
    return await service.request_kyc_document_upload_url(
        db=db,
        redis=redis,
        user=current_user,
        payload=payload,
    )


@router.post(
    "/kyc/documents/{document_id}/confirm",
    response_model=KycDocumentResponse,
    summary="Confirm an uploaded identity document",
    description=(
        "Confirms that the file reached storage, queues the malware scan, and "
        "moves the account to `pending` so it enters the admin review queue. "
        "Idempotent."
    ),
)
async def confirm_kyc_document(
    document_id: UUID,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> KycDocumentResponse:
    """Confirm an uploaded identity document and open it for review."""
    return await service.confirm_kyc_document(
        db=db,
        user=current_user,
        document_id=document_id,
    )


@router.post("/kyc/sync", response_model=KycStatusResponse)
async def sync_kyc_from_return(
    payload: KycSyncRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> KycStatusResponse:
    """Reconcile KYC state from a returned Persona inquiry.

    Reads the inquiry's verdict directly from Persona (server-to-server) and
    applies it, so a completed check resolves on return without waiting for the
    asynchronous webhook. Ownership-checked; idempotent.
    """
    return await service.sync_kyc_from_return(
        db=db,
        user=current_user,
        inquiry_id=payload.inquiry_id,
    )


@router.get("/sessions", response_model=SessionsResponse)
async def list_sessions(
    request: Request,
    current_user: CurrentUser,
    redis: RedisClient,
) -> SessionsResponse:
    """Return active browser refresh-token sessions for the current user."""
    return await service.list_sessions(
        redis=redis,
        user=current_user,
        current_refresh_token=request.cookies.get(REFRESH_COOKIE_NAME),
    )


@router.get(
    "/notification-preferences",
    response_model=NotificationPreferencesResponse,
)
async def get_notification_preferences(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> NotificationPreferencesResponse:
    """Return the authenticated user's effective notification preference matrix."""
    return await notification_preferences.build_preference_matrix(
        db=db,
        user_id=current_user.id,
    )


@router.patch(
    "/notification-preferences",
    response_model=NotificationPreferencesResponse,
)
async def update_notification_preferences(
    payload: NotificationPreferencesUpdateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> NotificationPreferencesResponse:
    """Persist owner-scoped notification preference updates."""
    return await notification_preferences.update_preferences(
        db=db,
        user_id=current_user.id,
        updates=payload.updates,
    )


@router.delete("/sessions/{session_id}", response_model=RegisterResponse)
async def revoke_session(
    session_id: str,
    request: Request,
    response: Response,
    current_user: CurrentUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> RegisterResponse:
    """Revoke one browser refresh-token session."""
    revoked_current = await service.revoke_session(
        db=db,
        redis=redis,
        user=current_user,
        session_id=session_id,
        current_refresh_token=request.cookies.get(REFRESH_COOKIE_NAME),
    )
    if revoked_current:
        clear_refresh_cookie(response)
        clear_session_hint_cookie(response)
    return RegisterResponse(message="Session revoked.")


@router.delete("/sessions", response_model=RegisterResponse)
async def revoke_other_sessions(
    request: Request,
    current_user: CurrentUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> RegisterResponse:
    """Revoke all browser refresh-token sessions except the current one."""
    revoked_count = await service.revoke_other_sessions(
        db=db,
        redis=redis,
        user=current_user,
        current_refresh_token=request.cookies.get(REFRESH_COOKIE_NAME),
    )
    return RegisterResponse(message=f"Revoked {revoked_count} sessions.")


@router.post("/account/email-change", response_model=RegisterResponse)
async def request_email_change(
    payload: EmailChangeRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> RegisterResponse:
    """Start a verified account email change."""
    await service.request_email_change(
        db=db,
        redis=redis,
        user=current_user,
        new_email=str(payload.new_email),
        password=(
            payload.password.get_secret_value()
            if payload.password is not None
            else None
        ),
        totp_code=payload.totp_code,
    )
    return RegisterResponse(message="Email change verification sent.")


@router.post("/account/email-change/confirm", response_model=RegisterResponse)
async def confirm_email_change(
    payload: EmailChangeConfirmRequest,
    db: DatabaseSession,
    redis: RedisClient,
) -> RegisterResponse:
    """Confirm a new account email address from the emailed token."""
    await service.confirm_email_change(db=db, redis=redis, token=payload.token)
    return RegisterResponse(message="Email changed.")
