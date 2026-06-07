"""FastAPI router for contributor Framework management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    require_kyc_verified,
    require_profile_complete,
    require_role,
)
from app.modules.auth.models import User
from app.modules.frameworks import service
from app.modules.frameworks.schemas import (
    FrameworkCreate,
    FrameworkListItem,
    FrameworkResponse,
    FrameworkUpdate,
)

router = APIRouter(prefix="/frameworks", tags=["Frameworks"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
ContributorUser = Annotated[User, Depends(require_role("contributor"))]
KycVerifiedUser = Annotated[User, Depends(require_kyc_verified)]
ProfileCompleteUser = Annotated[User, Depends(require_profile_complete)]


@router.post(
    "",
    response_model=FrameworkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_framework(
    payload: FrameworkCreate,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Create a draft Framework for the authenticated Contributor."""
    return await service.create_framework(
        db=db,
        contributor=contributor,
        payload=payload,
    )


@router.get("", response_model=list[FrameworkListItem])
async def list_frameworks(
    contributor: ContributorUser,
    db: DatabaseSession,
) -> list[FrameworkListItem]:
    """List Frameworks owned by the authenticated Contributor."""
    return await service.list_contributor_frameworks(db=db, contributor=contributor)


@router.get("/{framework_id}", response_model=FrameworkResponse)
async def get_framework(
    framework_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Return one Framework owned by the authenticated Contributor."""
    return await service.get_framework_for_contributor(
        db=db,
        contributor=contributor,
        framework_id=framework_id,
    )


@router.patch("/{framework_id}", response_model=FrameworkResponse)
async def update_framework(
    framework_id: UUID,
    payload: FrameworkUpdate,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Update an owned draft Framework."""
    return await service.update_framework(
        db=db,
        contributor=contributor,
        framework_id=framework_id,
        payload=payload,
    )


@router.delete("/{framework_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_framework(
    framework_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> Response:
    """Delete an owned draft Framework."""
    await service.delete_draft(
        db=db,
        contributor=contributor,
        framework_id=framework_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
