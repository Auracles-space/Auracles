"""FastAPI router for contributor Collection management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    require_kyc_verified,
    require_profile_complete,
    require_role,
)
from app.modules.auth.models import User
from app.modules.collections import service
from app.modules.collections.schemas import (
    CollectionCreateRequest,
    CollectionListResponse,
    CollectionMemberRequest,
    CollectionResponse,
    CollectionUpdateRequest,
)

router = APIRouter(prefix="/collections", tags=["Collections"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
ContributorUser = Annotated[User, Depends(require_role("contributor"))]
KycVerifiedUser = Annotated[User, Depends(require_kyc_verified)]
ProfileCompleteUser = Annotated[User, Depends(require_profile_complete)]


@router.post(
    "",
    response_model=CollectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_collection(
    payload: CollectionCreateRequest,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> CollectionResponse:
    """Create a draft Collection for the authenticated Contributor."""
    return await service.create_collection(
        db=db,
        contributor=contributor,
        payload=payload,
    )


@router.get("/mine", response_model=CollectionListResponse)
async def list_my_collections(
    contributor: ContributorUser,
    db: DatabaseSession,
) -> CollectionListResponse:
    """List Collections owned by the authenticated Contributor."""
    return await service.list_my_collections(db=db, contributor=contributor)


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    collection_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> CollectionResponse:
    """Return one Collection owned by the authenticated Contributor."""
    return await service.get_collection(
        db=db,
        contributor=contributor,
        collection_id=collection_id,
    )


@router.patch("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: UUID,
    payload: CollectionUpdateRequest,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> CollectionResponse:
    """Edit an owned draft or unpublished Collection."""
    return await service.update_collection(
        db=db,
        contributor=contributor,
        collection_id=collection_id,
        payload=payload,
    )


@router.post("/{collection_id}/members", response_model=CollectionResponse)
async def add_collection_member(
    collection_id: UUID,
    payload: CollectionMemberRequest,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> CollectionResponse:
    """Add an owned Framework to an editable Collection."""
    return await service.add_collection_member(
        db=db,
        contributor=contributor,
        collection_id=collection_id,
        payload=payload,
    )


@router.delete(
    "/{collection_id}/members/{framework_id}",
    response_model=CollectionResponse,
)
async def remove_collection_member(
    collection_id: UUID,
    framework_id: UUID,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> CollectionResponse:
    """Remove a Framework from an editable Collection."""
    return await service.remove_collection_member(
        db=db,
        contributor=contributor,
        collection_id=collection_id,
        framework_id=framework_id,
    )


@router.post("/{collection_id}/publish", response_model=CollectionResponse)
async def publish_collection(
    collection_id: UUID,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> CollectionResponse:
    """Publish an owned Collection after bundle validation passes."""
    return await service.publish_collection(
        db=db,
        contributor=contributor,
        collection_id=collection_id,
    )


@router.post("/{collection_id}/unpublish", response_model=CollectionResponse)
async def unpublish_collection(
    collection_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> CollectionResponse:
    """Unpublish an owned Collection so new catalog purchases stop."""
    return await service.unpublish_collection(
        db=db,
        contributor=contributor,
        collection_id=collection_id,
    )
