"""FastAPI router for GDPR and data-rights endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_current_user_allow_query
from app.core.redis import get_redis
from app.modules.auth.models import User
from app.modules.gdpr import consent_service, deletion_service, export_service
from app.modules.gdpr.schemas import (
    AccountDeletionRequestBody,
    AccountDeletionStatusResponse,
    ConsentAcceptRequest,
    ConsentHistoryResponse,
    DataExportRequestResponse,
)

router = APIRouter(prefix="/gdpr", tags=["GDPR"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
CurrentUser = Annotated[User, Depends(get_current_user)]
# Query-token auth is reserved for browser-navigated redirect downloads.
DownloadUser = Annotated[User, Depends(get_current_user_allow_query)]


def _client_ip(request: Request) -> str | None:
    """Return the client IP address when available."""
    return request.client.host if request.client else None


@router.post("/consent", response_model=ConsentHistoryResponse)
async def accept_current_consent(
    payload: ConsentAcceptRequest,
    request: Request,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ConsentHistoryResponse:
    """Record acceptance of the current legal document versions."""
    del payload
    user_id = current_user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await consent_service.record_current_consents(
            db=db,
            user_id=user_id,
            ip=_client_ip(request),
            ua=request.headers.get("user-agent"),
        )
    return await consent_service.get_consent_history(db=db, user_id=user_id)


@router.get("/consent", response_model=ConsentHistoryResponse)
async def list_consent_history(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ConsentHistoryResponse:
    """Return the user's consent status and append-only history."""
    return await consent_service.get_consent_history(db=db, user_id=current_user.id)


@router.post(
    "/exports",
    response_model=DataExportRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_data_export(
    current_user: CurrentUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> DataExportRequestResponse:
    """Request an async GDPR JSON data export for the current user."""
    return await export_service.request_data_export(
        db=db,
        redis=redis,
        user=current_user,
    )


@router.get("/exports/latest", response_model=DataExportRequestResponse)
async def get_latest_data_export_status(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DataExportRequestResponse:
    """Return the current user's latest GDPR data export request status."""
    return await export_service.get_latest_data_export_status(
        db=db,
        user_id=current_user.id,
    )


@router.get("/exports/{export_request_id}", response_model=DataExportRequestResponse)
async def get_data_export_status(
    export_request_id: UUID,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DataExportRequestResponse:
    """Return the current user's GDPR data export request status."""
    return await export_service.get_data_export_status(
        db=db,
        user_id=current_user.id,
        export_request_id=export_request_id,
    )


@router.get(
    "/exports/{export_request_id}/download",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    summary="Download GDPR export",
    description=(
        "Redirect the current user to a short-lived private S3 download URL for "
        "a ready GDPR export bundle."
    ),
    responses={
        status.HTTP_302_FOUND: {"description": "Private presigned download URL."},
        status.HTTP_404_NOT_FOUND: {"description": "Data export request not found."},
        status.HTTP_409_CONFLICT: {
            "description": "Data export is not ready for download."
        },
        status.HTTP_410_GONE: {"description": "Data export has expired."},
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": "Too many attempts; see the Retry-After header."
        },
    },
)
async def download_data_export(
    export_request_id: UUID,
    current_user: DownloadUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> Response:
    """Return a presigned GDPR export download redirect for the current user."""
    return await export_service.download_data_export(
        db=db,
        redis=redis,
        user_id=current_user.id,
        export_request_id=export_request_id,
    )


@router.post(
    "/account-deletion",
    response_model=AccountDeletionStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request account deletion",
    description=(
        "Schedule GDPR account deletion after password confirmation and the "
        "configured cooling-off period."
    ),
    responses={
        status.HTTP_202_ACCEPTED: {
            "description": "Account deletion scheduled during cooling-off."
        },
        status.HTTP_409_CONFLICT: {
            "model": AccountDeletionStatusResponse,
            "description": "Account deletion is blocked by active obligations.",
        },
    },
)
async def request_account_deletion(
    payload: AccountDeletionRequestBody,
    current_user: CurrentUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> Response:
    """Schedule account deletion for the current user."""
    result, status_code = await deletion_service.request_account_deletion(
        db=db,
        redis=redis,
        user=current_user,
        payload=payload,
    )
    return JSONResponse(
        status_code=status_code,
        content=result.model_dump(mode="json"),
    )


@router.get(
    "/account-deletion",
    response_model=AccountDeletionStatusResponse,
    summary="Get account deletion status",
    description="Return the latest GDPR account-deletion request for the current user.",
)
async def get_account_deletion_status(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AccountDeletionStatusResponse:
    """Return the latest GDPR account-deletion request for the current user."""
    return await deletion_service.get_account_deletion_status(
        db=db,
        user_id=current_user.id,
    )


@router.post(
    "/account-deletion/cancel",
    response_model=AccountDeletionStatusResponse,
    summary="Cancel account deletion",
    description=(
        "Cancel the current user's scheduled GDPR account deletion during the "
        "cooling-off window."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Account deletion request not found."
        }
    },
)
async def cancel_account_deletion(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AccountDeletionStatusResponse:
    """Cancel the current user's scheduled GDPR account deletion."""
    return await deletion_service.cancel_account_deletion(
        db=db,
        user_id=current_user.id,
    )
