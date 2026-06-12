"""FastAPI router for admin endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.core.redis import get_redis
from app.modules.admin import service
from app.modules.admin.schemas import (
    AdminAnalyticsDashboardResponse,
    AdminConfigItem,
    AdminConfigPatchRequest,
    AdminConfigResponse,
    AdminDisputeResolveRequest,
    AdminEscrowOverrideRequest,
    AdminEscrowResponse,
    AdminFrameworkStatusResponse,
    AdminFrameworkSuspendRequest,
    AdminKycReviewRequest,
    AdminKycReviewResponse,
    AdminLicenseGrantRequest,
    AdminLicenseGrantResponse,
    AdminRarityBlockOverrideRequest,
    AdminRoleAssignmentRequest,
    AdminRoleAssignmentResponse,
)
from app.modules.auth.models import User
from app.modules.financials.models import Escrow, PlatformConfig
from app.modules.projects import dispute_service
from app.modules.projects.schemas import DisputeResponse

router = APIRouter(prefix="/admin", tags=["Admin"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
AdminUser = Annotated[User, Depends(require_role("admin"))]


def _escrow_response(escrow: Escrow) -> AdminEscrowResponse:
    """Map an escrow model to an admin response schema."""
    return AdminEscrowResponse(
        escrow_id=escrow.id,
        transaction_id=escrow.transaction_id,
        ref_id=escrow.ref_id,
        ref_type=escrow.ref_type,
        amount=str(escrow.amount),
        currency=escrow.currency,
        status=escrow.status,
        released_at=escrow.released_at,
        released_by=escrow.released_by,
    )


def _config_response(items: list[PlatformConfig]) -> AdminConfigResponse:
    """Map config model rows to the admin response schema."""
    return AdminConfigResponse(
        items=[
            AdminConfigItem(
                key=item.key,
                value=item.value,
                editable=item.key in service.EDITABLE_PLATFORM_CONFIG_KEYS,
                updated_at=item.updated_at,
                updated_by=item.updated_by,
            )
            for item in items
        ]
    )


@router.get("/config", response_model=AdminConfigResponse)
async def list_platform_config(
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminConfigResponse:
    """List platform financial configuration for admin review."""
    del admin
    items = await service.list_platform_config(db=db)
    return _config_response(items)


@router.get(
    "/analytics/dashboard",
    response_model=AdminAnalyticsDashboardResponse,
    summary="Get admin dashboard analytics",
    description=(
        "Return current-state admin analytics aggregates. Slice 2 excludes "
        "historical trend rows until snapshot-backed analytics land."
    ),
)
async def get_admin_analytics_dashboard(
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminAnalyticsDashboardResponse:
    """Return current-state analytics for the admin dashboard."""
    del admin
    dashboard = await service.get_dashboard_analytics(db=db)
    return AdminAnalyticsDashboardResponse.model_validate(dashboard)


@router.patch("/config", response_model=AdminConfigResponse)
async def update_platform_config(
    payload: AdminConfigPatchRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AdminConfigResponse:
    """Update editable platform financial configuration with admin 2FA."""
    items = await service.update_platform_config(
        db=db,
        redis=redis,
        admin=admin,
        updates=[(item.key, item.value) for item in payload.updates],
        reason=payload.reason,
        totp_code=payload.totp_code,
    )
    return _config_response(items)


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
    "/frameworks/{framework_id}/rarity-block/override",
    response_model=AdminFrameworkStatusResponse,
)
async def override_rarity_block(
    framework_id: UUID,
    payload: AdminRarityBlockOverrideRequest,
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminFrameworkStatusResponse:
    """Override a near-duplicate rarity hard block after admin review."""
    framework = await service.override_rarity_block(
        db=db,
        admin=admin,
        framework_id=framework_id,
        reason=payload.reason,
    )
    return AdminFrameworkStatusResponse(
        framework_id=framework.id,
        status=framework.status,
        reason=payload.reason,
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


@router.post(
    "/escrows/{escrow_id}/release",
    response_model=AdminEscrowResponse,
)
async def release_escrow(
    escrow_id: UUID,
    payload: AdminEscrowOverrideRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AdminEscrowResponse:
    """Release held escrow funds through an audited admin override."""
    escrow = await service.release_escrow_override(
        db=db,
        redis=redis,
        admin=admin,
        escrow_id=escrow_id,
        reason=payload.reason,
        totp_code=payload.totp_code,
    )
    return _escrow_response(escrow)


@router.post(
    "/escrows/{escrow_id}/refund",
    response_model=AdminEscrowResponse,
)
async def refund_escrow(
    escrow_id: UUID,
    payload: AdminEscrowOverrideRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AdminEscrowResponse:
    """Refund held escrow funds through an audited admin override."""
    escrow = await service.refund_escrow_override(
        db=db,
        redis=redis,
        admin=admin,
        escrow_id=escrow_id,
        reason=payload.reason,
        totp_code=payload.totp_code,
    )
    return _escrow_response(escrow)


@router.post(
    "/projects/disputes/{dispute_id}/resolve",
    response_model=DisputeResponse,
)
async def resolve_project_dispute(
    dispute_id: UUID,
    payload: AdminDisputeResolveRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> DisputeResponse:
    """Resolve a Project dispute through an audited 2FA-gated admin action."""
    dispute = await dispute_service.resolve_dispute(
        db=db,
        redis=redis,
        admin=admin,
        dispute_id=dispute_id,
        resolution_type=payload.resolution_type,
        release_amount=payload.release_amount,
        refund_amount=payload.refund_amount,
        resolution_notes=payload.resolution_notes,
        totp_code=payload.totp_code,
    )
    return DisputeResponse.model_validate(dispute)
