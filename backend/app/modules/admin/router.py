"""FastAPI router for admin endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.modules.admin import service
from app.modules.admin.schemas import (
    AdminRoleAssignmentRequest,
    AdminRoleAssignmentResponse,
)
from app.modules.auth.models import User

router = APIRouter(prefix="/admin", tags=["Admin"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
AdminUser = Annotated[User, Depends(require_role("admin"))]


@router.patch("/users/{user_id}/roles", response_model=AdminRoleAssignmentResponse)
async def assign_role(
    user_id: UUID,
    payload: AdminRoleAssignmentRequest,
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminRoleAssignmentResponse:
    """Assign or approve a user role."""
    assigned_role = await service.assign_user_role(
        db=db,
        admin=admin,
        target_user_id=user_id,
        role=payload.role,
    )
    return AdminRoleAssignmentResponse(
        user_id=user_id,
        role=assigned_role.role,
        approved=assigned_role.approved_at is not None,
    )
