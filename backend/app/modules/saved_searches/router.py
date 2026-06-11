"""FastAPI router for Operator saved-search management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.modules.auth.models import User
from app.modules.saved_searches import service
from app.modules.saved_searches.schemas import (
    SavedSearchCreateRequest,
    SavedSearchListResponse,
    SavedSearchResponse,
    SavedSearchUpdateRequest,
)

router = APIRouter(prefix="/saved-searches", tags=["Saved Searches"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
OperatorUser = Annotated[User, Depends(require_role("operator"))]


@router.post(
    "",
    response_model=SavedSearchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_saved_search(
    payload: SavedSearchCreateRequest,
    operator: OperatorUser,
    db: DatabaseSession,
) -> SavedSearchResponse:
    """Create an Operator-owned saved Explore search."""
    return await service.create_saved_search(
        db=db,
        operator=operator,
        payload=payload,
    )


@router.get("", response_model=SavedSearchListResponse)
async def list_saved_searches(
    operator: OperatorUser,
    db: DatabaseSession,
) -> SavedSearchListResponse:
    """List saved searches owned by the authenticated Operator."""
    return await service.list_saved_searches(db=db, operator=operator)


@router.patch("/{saved_search_id}", response_model=SavedSearchResponse)
async def update_saved_search(
    saved_search_id: UUID,
    payload: SavedSearchUpdateRequest,
    operator: OperatorUser,
    db: DatabaseSession,
) -> SavedSearchResponse:
    """Edit an Operator-owned saved search."""
    return await service.update_saved_search(
        db=db,
        operator=operator,
        saved_search_id=saved_search_id,
        payload=payload,
    )


@router.delete(
    "/{saved_search_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_saved_search(
    saved_search_id: UUID,
    operator: OperatorUser,
    db: DatabaseSession,
) -> Response:
    """Delete an Operator-owned saved search."""
    await service.delete_saved_search(
        db=db,
        operator=operator,
        saved_search_id=saved_search_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
