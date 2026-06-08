"""FastAPI router for admin endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.modules.admin import service
from app.modules.admin.schemas import (
    AdminFrameworkStatusResponse,
    AdminFrameworkSuspendRequest,
    AdminKycReviewRequest,
    AdminKycReviewResponse,
    AdminLicenseGrantRequest,
    AdminLicenseGrantResponse,
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


@router.patch("/users/{user_id}/kyc", response_model=AdminKycReviewResponse)
async def review_kyc(
    user_id: UUID,
    payload: AdminKycReviewRequest,
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminKycReviewResponse:
    """Review a user's latest KYC document."""
    document = await service.review_user_kyc(
        db=db,
        admin=admin,
        target_user_id=user_id,
        review_status=payload.status,
        notes=payload.notes,
    )
    return AdminKycReviewResponse(
        user_id=user_id,
        kyc_status=document.status,
        document_status=document.status,
    )


@router.post(
    "/frameworks/{framework_id}/suspend",
    response_model=AdminFrameworkStatusResponse,
)
async def suspend_framework(
    framework_id: UUID,
    payload: AdminFrameworkSuspendRequest,
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminFrameworkStatusResponse:
    """Suspend a published Framework from marketplace discovery."""
    framework = await service.suspend_framework(
        db=db,
        admin=admin,
        framework_id=framework_id,
        reason=payload.reason,
    )
    return AdminFrameworkStatusResponse(
        framework_id=framework.id,
        status=framework.status,
        reason=framework.rejection_reason,
    )


@router.post(
    "/licenses",
    response_model=AdminLicenseGrantResponse,
    status_code=201,
)
async def grant_license(
    payload: AdminLicenseGrantRequest,
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminLicenseGrantResponse:
    """Grant a Framework license to an Operator during Phase 2."""
    license_row = await service.grant_license(
        db=db,
        admin=admin,
        framework_id=payload.framework_id,
        operator_id=payload.operator_id,
        license_type=payload.type,
        expires_at=payload.expires_at,
        seats_total=payload.seats_total,
    )
    return AdminLicenseGrantResponse(
        license_id=license_row.id,
        framework_id=license_row.framework_id,
        operator_id=license_row.operator_id,
        type=license_row.license_type,
        status=license_row.status,
        version_at_grant=license_row.version_at_grant,
        seats_used=license_row.seats_used,
        seats_total=license_row.seats_total,
        expires_at=license_row.expires_at,
    )
