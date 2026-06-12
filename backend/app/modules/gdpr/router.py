"""FastAPI router for GDPR and data-rights endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.gdpr import consent_service
from app.modules.gdpr.schemas import ConsentAcceptRequest, ConsentHistoryResponse

router = APIRouter(prefix="/gdpr", tags=["GDPR"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


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
