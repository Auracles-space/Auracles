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
from app.modules.profiles.schemas import PublicProfileResponse

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
