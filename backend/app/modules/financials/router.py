"""Financials API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_kyc_verified, require_role
from app.core.redis import get_redis
from app.modules.auth.models import User
from app.modules.financials import service
from app.modules.financials.schemas import (
    PaymentMethodDeleteRequest,
    PaymentMethodDeleteResponse,
    PaymentMethodSetupRequest,
    PaymentMethodSetupResponse,
    PaymentMethodsResponse,
    PayoutAccountDeleteRequest,
    PayoutAccountDeleteResponse,
    PayoutAccountOnboardRequest,
    PayoutAccountOnboardResponse,
    PayoutAccountsResponse,
    PurchaseRequest,
    PurchaseResponse,
    RefundResponse,
)

router = APIRouter(prefix="/financials", tags=["Financials"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
OperatorUser = Annotated[User, Depends(require_role("operator"))]
ContributorUser = Annotated[User, Depends(require_role("contributor"))]
KycVerifiedUser = Annotated[User, Depends(require_kyc_verified)]


@router.post("/payment-methods", response_model=PaymentMethodSetupResponse)
async def create_payment_method_setup(
    payload: PaymentMethodSetupRequest,
    operator: OperatorUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> PaymentMethodSetupResponse:
    """Start provider-hosted setup for an Operator payment method."""
    return await service.create_payment_method_setup(
        db=db,
        redis=redis,
        operator=operator,
        totp_code=payload.totp_code,
    )


@router.get("/payment-methods", response_model=PaymentMethodsResponse)
async def list_payment_methods(
    operator: OperatorUser,
    db: DatabaseSession,
) -> PaymentMethodsResponse:
    """List safe metadata for the Operator's provider-held payment methods."""
    return await service.list_payment_methods(db=db, operator=operator)


@router.delete(
    "/payment-methods/{payment_method_id}",
    response_model=PaymentMethodDeleteResponse,
)
async def delete_payment_method(
    payment_method_id: str,
    payload: PaymentMethodDeleteRequest,
    operator: OperatorUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> PaymentMethodDeleteResponse:
    """Remove a provider-held payment method for the authenticated Operator."""
    return await service.delete_payment_method(
        db=db,
        redis=redis,
        operator=operator,
        payment_method_id=payment_method_id,
        totp_code=payload.totp_code,
    )


@router.post("/purchase/{framework_id}", response_model=PurchaseResponse)
async def create_framework_purchase(
    framework_id: UUID,
    payload: PurchaseRequest,
    operator: OperatorUser,
    db: DatabaseSession,
) -> PurchaseResponse:
    """Start Stripe checkout for a published self-serve Framework license."""
    return await service.create_framework_purchase(
        db=db,
        operator=operator,
        framework_id=framework_id,
        payload=payload,
    )


@router.post(
    "/purchases/{transaction_id}/refund",
    response_model=RefundResponse,
)
async def refund_framework_purchase(
    transaction_id: UUID,
    operator: OperatorUser,
    db: DatabaseSession,
) -> RefundResponse:
    """Refund an eligible completed Framework purchase for the Operator."""
    return await service.refund_framework_purchase(
        db=db,
        operator=operator,
        transaction_id=transaction_id,
    )


@router.post(
    "/payout-accounts/onboard",
    response_model=PayoutAccountOnboardResponse,
)
async def onboard_payout_account(
    payload: PayoutAccountOnboardRequest,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    db: DatabaseSession,
) -> PayoutAccountOnboardResponse:
    """Create a Stripe Express payout account for a verified Contributor."""
    return await service.onboard_payout_account(
        db=db,
        contributor=contributor,
        payload=payload,
    )


@router.get("/payout-accounts", response_model=PayoutAccountsResponse)
async def list_payout_accounts(
    contributor: ContributorUser,
    db: DatabaseSession,
) -> PayoutAccountsResponse:
    """List active payout accounts for the authenticated Contributor."""
    return await service.list_payout_accounts(db=db, contributor=contributor)


@router.delete(
    "/payout-accounts/{payout_account_id}",
    response_model=PayoutAccountDeleteResponse,
)
async def delete_payout_account(
    payout_account_id: UUID,
    payload: PayoutAccountDeleteRequest,
    contributor: ContributorUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> PayoutAccountDeleteResponse:
    """Soft-delete an owned payout account after 2FA confirmation."""
    return await service.delete_payout_account(
        db=db,
        redis=redis,
        contributor=contributor,
        payout_account_id=payout_account_id,
        totp_code=payload.totp_code,
    )
