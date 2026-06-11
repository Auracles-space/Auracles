"""Developer platform API router."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.redis import get_redis
from app.modules.auth.models import User
from app.modules.developer import application_service
from app.modules.developer.schemas import (
    DeveloperApplicationCreateRequest,
    DeveloperApplicationResponse,
    DeveloperApplicationReviewRequest,
    DeveloperApplicationsResponse,
)

router = APIRouter(tags=["Developer"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_role("admin"))]


@router.post(
    "/developer/applications",
    response_model=DeveloperApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_developer_application(
    payload: DeveloperApplicationCreateRequest,
    user: CurrentUser,
    db: DatabaseSession,
) -> DeveloperApplicationResponse:
    """Submit a Developer application as any authenticated user."""
    application = await application_service.submit_application(
        db=db,
        user=user,
        payload=payload,
    )
    return DeveloperApplicationResponse.model_validate(application)


@router.get(
    "/developer/applications/mine",
    response_model=DeveloperApplicationsResponse,
)
async def list_my_developer_applications(
    user: CurrentUser,
    db: DatabaseSession,
) -> DeveloperApplicationsResponse:
    """List the authenticated user's Developer application history."""
    applications = await application_service.list_my_applications(db=db, user=user)
    return DeveloperApplicationsResponse(
        applications=[
            DeveloperApplicationResponse.model_validate(application)
            for application in applications
        ]
    )


@router.patch(
    "/developer/applications/{application_id}/withdraw",
    response_model=DeveloperApplicationResponse,
)
async def withdraw_developer_application(
    application_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
) -> DeveloperApplicationResponse:
    """Withdraw a pending Developer application owned by the current user."""
    application = await application_service.withdraw_application(
        db=db,
        user=user,
        application_id=application_id,
    )
    return DeveloperApplicationResponse.model_validate(application)


@router.get(
    "/admin/developer/applications",
    response_model=DeveloperApplicationsResponse,
)
async def list_developer_applications_for_admin(
    admin: AdminUser,
    db: DatabaseSession,
    status_filter: Literal[
        "pending",
        "approved",
        "rejected",
        "withdrawn",
    ]
    | None = Query(default=None, alias="status"),
) -> DeveloperApplicationsResponse:
    """List Developer applications for admin review."""
    del admin
    applications = await application_service.list_applications_for_admin(
        db=db,
        status_filter=status_filter,
    )
    return DeveloperApplicationsResponse(
        applications=[
            DeveloperApplicationResponse.model_validate(application)
            for application in applications
        ]
    )


@router.post(
    "/admin/developer/applications/{application_id}/review",
    response_model=DeveloperApplicationResponse,
)
async def review_developer_application(
    application_id: UUID,
    payload: DeveloperApplicationReviewRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> DeveloperApplicationResponse:
    """Approve or reject a Developer application as a 2FA-confirmed admin."""
    application = await application_service.review_application(
        db=db,
        redis=redis,
        admin=admin,
        application_id=application_id,
        payload=payload,
    )
    return DeveloperApplicationResponse.model_validate(application)
