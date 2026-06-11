"""Developer platform API router."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_kyc_verified, require_role
from app.core.redis import get_redis
from app.modules.auth.models import User
from app.modules.developer import (
    analytics_service,
    application_service,
    commission_service,
    keys_service,
    webhooks_service,
)
from app.modules.developer.dependencies import require_active_developer_account
from app.modules.developer.models import DeveloperAccount
from app.modules.developer.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyResponse,
    ApiKeysResponse,
    ApiKeyUpdateRequest,
    DeveloperApplicationCreateRequest,
    DeveloperApplicationResponse,
    DeveloperApplicationReviewRequest,
    DeveloperApplicationsResponse,
    DeveloperSalesAnalyticsResponse,
    DeveloperTierProgressResponse,
    DeveloperUsageAnalyticsResponse,
    PartnerPayoutRequest,
    PartnerPayoutResponse,
    PartnerPayoutsResponse,
    PartnerWebhookCreateRequest,
    PartnerWebhookCreateResponse,
    PartnerWebhookDeliveryResponse,
    PartnerWebhookResponse,
    PartnerWebhooksResponse,
)

router = APIRouter(tags=["Developer"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_role("admin"))]
KycVerifiedUser = Annotated[User, Depends(require_kyc_verified)]
ActiveDeveloperAccount = Annotated[
    DeveloperAccount,
    Depends(require_active_developer_account),
]


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


@router.post(
    "/developer/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    payload: ApiKeyCreateRequest,
    developer_account: ActiveDeveloperAccount,
    db: DatabaseSession,
) -> ApiKeyCreateResponse:
    """Create a scoped API key and return the raw key exactly once."""
    api_key, raw_key = await keys_service.create_api_key(
        db=db,
        developer_account=developer_account,
        payload=payload,
    )
    return ApiKeyCreateResponse(
        **ApiKeyResponse.model_validate(api_key).model_dump(),
        raw_key=raw_key,
    )


@router.get("/developer/api-keys", response_model=ApiKeysResponse)
async def list_api_keys(
    developer_account: ActiveDeveloperAccount,
    db: DatabaseSession,
) -> ApiKeysResponse:
    """List API key metadata for the active Developer account."""
    api_keys = await keys_service.list_api_keys(
        db=db,
        developer_account=developer_account,
    )
    return ApiKeysResponse(
        api_keys=[ApiKeyResponse.model_validate(api_key) for api_key in api_keys]
    )


@router.get("/developer/tier", response_model=DeveloperTierProgressResponse)
async def get_developer_tier_progress(
    developer_account: ActiveDeveloperAccount,
    db: DatabaseSession,
) -> DeveloperTierProgressResponse:
    """Return Partner commission tier and next-tier progress."""
    return await commission_service.get_tier_progress(
        db,
        developer_account=developer_account,
    )


@router.post("/developer/payouts", response_model=PartnerPayoutResponse)
async def request_partner_payout(
    payload: PartnerPayoutRequest,
    user: CurrentUser,
    _: KycVerifiedUser,
    developer_account: ActiveDeveloperAccount,
    db: DatabaseSession,
    redis: RedisClient,
) -> PartnerPayoutResponse:
    """Request withdrawal of cleared Partner commission balance."""
    return await commission_service.request_partner_payout(
        db,
        redis,
        developer_account=developer_account,
        user=user,
        payload=payload,
    )


@router.get("/developer/payouts", response_model=PartnerPayoutsResponse)
async def list_partner_payouts(
    developer_account: ActiveDeveloperAccount,
    db: DatabaseSession,
) -> PartnerPayoutsResponse:
    """List Partner payout history for the active Developer account."""
    return await commission_service.list_partner_payouts(
        db,
        developer_account=developer_account,
    )


@router.get(
    "/developer/analytics/usage",
    response_model=DeveloperUsageAnalyticsResponse,
)
async def get_developer_usage_analytics(
    developer_account: ActiveDeveloperAccount,
    db: DatabaseSession,
    days: int = Query(default=30, ge=1, le=365),
) -> DeveloperUsageAnalyticsResponse:
    """Return aggregate Partner API usage analytics for the Developer."""
    return await analytics_service.get_usage_analytics(
        db,
        developer_account=developer_account,
        days=days,
    )


@router.get(
    "/developer/analytics/sales",
    response_model=DeveloperSalesAnalyticsResponse,
)
async def get_developer_sales_analytics(
    developer_account: ActiveDeveloperAccount,
    db: DatabaseSession,
    days: int = Query(default=30, ge=1, le=365),
) -> DeveloperSalesAnalyticsResponse:
    """Return aggregate Partner sales and commission analytics."""
    return await analytics_service.get_sales_analytics(
        db,
        developer_account=developer_account,
        days=days,
    )


@router.post(
    "/developer/webhooks",
    response_model=PartnerWebhookCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_partner_webhook(
    payload: PartnerWebhookCreateRequest,
    developer_account: ActiveDeveloperAccount,
    db: DatabaseSession,
) -> PartnerWebhookCreateResponse:
    """Register a Partner outbound webhook and return its raw secret once."""
    webhook, raw_secret = await webhooks_service.create_partner_webhook(
        db=db,
        developer_account=developer_account,
        payload=payload,
    )
    return PartnerWebhookCreateResponse(
        **PartnerWebhookResponse.model_validate(webhook).model_dump(),
        secret=raw_secret,
    )


@router.get("/developer/webhooks", response_model=PartnerWebhooksResponse)
async def list_partner_webhooks(
    developer_account: ActiveDeveloperAccount,
    db: DatabaseSession,
) -> PartnerWebhooksResponse:
    """List Partner outbound webhook metadata for the active Developer."""
    webhooks = await webhooks_service.list_partner_webhooks(
        db=db,
        developer_account=developer_account,
    )
    return PartnerWebhooksResponse(
        webhooks=[
            PartnerWebhookResponse.model_validate(webhook) for webhook in webhooks
        ]
    )


@router.delete(
    "/developer/webhooks/{webhook_id}",
    response_model=PartnerWebhookResponse,
)
async def delete_partner_webhook(
    webhook_id: UUID,
    developer_account: ActiveDeveloperAccount,
    db: DatabaseSession,
) -> PartnerWebhookResponse:
    """Deactivate a Partner webhook endpoint owned by the active Developer."""
    webhook = await webhooks_service.delete_partner_webhook(
        db=db,
        developer_account=developer_account,
        webhook_id=webhook_id,
    )
    return PartnerWebhookResponse.model_validate(webhook)


@router.post(
    "/developer/webhooks/deliveries/{delivery_id}/retry",
    response_model=PartnerWebhookDeliveryResponse,
)
async def retry_partner_webhook_delivery(
    delivery_id: UUID,
    developer_account: ActiveDeveloperAccount,
    db: DatabaseSession,
) -> PartnerWebhookDeliveryResponse:
    """Manually retry a failed or dead Partner webhook delivery."""
    delivery = await webhooks_service.retry_partner_webhook_delivery(
        db=db,
        developer_account=developer_account,
        delivery_id=delivery_id,
    )
    return PartnerWebhookDeliveryResponse.model_validate(delivery)


@router.patch(
    "/developer/api-keys/{api_key_id}",
    response_model=ApiKeyResponse,
)
async def update_api_key(
    api_key_id: UUID,
    payload: ApiKeyUpdateRequest,
    developer_account: ActiveDeveloperAccount,
    db: DatabaseSession,
) -> ApiKeyResponse:
    """Update the display label for an API key owned by the Developer."""
    api_key = await keys_service.update_api_key(
        db=db,
        developer_account=developer_account,
        api_key_id=api_key_id,
        payload=payload,
    )
    return ApiKeyResponse.model_validate(api_key)


@router.delete(
    "/developer/api-keys/{api_key_id}",
    response_model=ApiKeyResponse,
)
async def revoke_api_key(
    api_key_id: UUID,
    developer_account: ActiveDeveloperAccount,
    db: DatabaseSession,
) -> ApiKeyResponse:
    """Revoke an API key owned by the active Developer account."""
    api_key = await keys_service.revoke_api_key(
        db=db,
        developer_account=developer_account,
        api_key_id=api_key_id,
    )
    return ApiKeyResponse.model_validate(api_key)
