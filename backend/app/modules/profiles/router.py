"""FastAPI router for the Auracles Profile module.

Thin layer: parse the request, call the profile service, return the curated
public response. No business logic or DB access here.

Maps to: FR-SET-001/002.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.profiles import service
from app.modules.profiles.schemas import (
    AvatarConfirmRequest,
    AvatarUploadUrlRequest,
    AvatarUploadUrlResponse,
    BannerConfirmRequest,
    BannerUploadUrlRequest,
    BannerUploadUrlResponse,
    ProfileUpdateRequest,
    PublicProfileResponse,
)

router = APIRouter(prefix="/profiles", tags=["Profiles"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get(
    "/me",
    response_model=PublicProfileResponse,
    summary="Get my own profile",
    description=(
        "Return the authenticated user's own profile. The owner always sees "
        "their full content; the is_limited flag reflects moderation state."
    ),
)
async def get_my_profile(
    db: DatabaseSession,
    current_user: CurrentUser,
) -> PublicProfileResponse:
    """Return the authenticated owner's own profile."""
    return await service.get_own_profile(db, user=current_user)


@router.patch(
    "/me",
    response_model=PublicProfileResponse,
    summary="Update my profile",
    description=(
        "Update the authenticated user's editable profile fields (headline, "
        "bio, location, website). Partial update: omitted fields are unchanged."
    ),
)
async def update_my_profile(
    payload: ProfileUpdateRequest,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> PublicProfileResponse:
    """Apply the owner's partial profile edit."""
    return await service.update_profile(db, user=current_user, payload=payload)


@router.post(
    "/me/avatar/upload-url",
    response_model=AvatarUploadUrlResponse,
    summary="Request an avatar upload URL",
    description=(
        "Return a presigned POST target for the authenticated user's avatar. "
        "Image type and size are validated before the target is issued."
    ),
)
async def request_avatar_upload_url(
    payload: AvatarUploadUrlRequest,
    current_user: CurrentUser,
) -> AvatarUploadUrlResponse:
    """Return a presigned avatar upload target for the owner."""
    return await service.request_avatar_upload_url(user=current_user, payload=payload)


@router.post(
    "/me/avatar/confirm",
    response_model=PublicProfileResponse,
    summary="Confirm an avatar upload",
    description=(
        "Confirm a completed avatar upload and publish it on the profile. "
        "The object must exist and the key must belong to the caller."
    ),
)
async def confirm_avatar_upload(
    payload: AvatarConfirmRequest,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> PublicProfileResponse:
    """Persist the owner's avatar after verifying the upload."""
    return await service.confirm_avatar_upload(db, user=current_user, payload=payload)


@router.post(
    "/me/banner/upload-url",
    response_model=BannerUploadUrlResponse,
    summary="Request a banner upload URL",
    description=(
        "Return a presigned POST target for the authenticated user's profile "
        "banner. Image type and size are validated before the target is issued."
    ),
)
async def request_banner_upload_url(
    payload: BannerUploadUrlRequest,
    current_user: CurrentUser,
) -> BannerUploadUrlResponse:
    """Return a presigned banner upload target for the owner."""
    return await service.request_banner_upload_url(user=current_user, payload=payload)


@router.post(
    "/me/banner/confirm",
    response_model=PublicProfileResponse,
    summary="Confirm a banner upload",
    description=(
        "Confirm a completed banner upload and publish it on the profile. "
        "The object must exist and the key must belong to the caller."
    ),
)
async def confirm_banner_upload(
    payload: BannerConfirmRequest,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> PublicProfileResponse:
    """Persist the owner's banner after verifying the upload."""
    return await service.confirm_banner_upload(db, user=current_user, payload=payload)


@router.get(
    "/{user_id}",
    response_model=PublicProfileResponse,
    summary="Get a public profile",
    description=(
        "Return the curated public profile for any platform user: identity, "
        "role badges, and KYC verification status. Private account fields are "
        "never included."
    ),
)
async def get_public_profile(
    user_id: UUID,
    db: DatabaseSession,
) -> PublicProfileResponse:
    """Return the curated public profile for the given user."""
    return await service.get_public_profile(db, user_id=user_id)
