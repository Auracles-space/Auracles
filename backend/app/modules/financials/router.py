"""Financials API routes."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    require_kyc_verified,
    require_role,
    require_step_up_after,
)
from app.core.rate_limit import RedisCounter
from app.core.redis import get_redis
from app.modules.auth.models import User
from app.modules.collections import service as collections_service
from app.modules.financials import service
from app.modules.financials.schemas import (
    EarningsResponse,
    PaymentMethodDeleteRequest,
    PaymentMethodDeleteResponse,
    PaymentMethodSetupRequest,
    PaymentMethodSetupResponse,
    PaymentMethodsResponse,
    PayoutAccountDeleteRequest,
    PayoutAccountDeleteResponse,
    PayoutAccountOnboardRequest,
    PayoutAccountOnboardResponse,
    PayoutAccountResolveRequest,
    PayoutAccountResolveResponse,
    PayoutAccountsResponse,
    PayoutBanksResponse,
    PayoutRequest,
    PayoutResponse,
    PayoutsResponse,
    PurchaseHistoryResponse,
    PurchaseRequest,
    PurchaseResponse,
    RefundResponse,
)

router = APIRouter(prefix="/financials", tags=["Financials"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
OperatorUser = Annotated[User, Depends(require_role("operator"))]
# Query-token auth is reserved for browser-navigated redirect downloads.
ContributorUser = Annotated[User, Depends(require_role("contributor"))]
KycVerifiedUser = Annotated[User, Depends(require_kyc_verified)]
RedisConnection = Annotated[Redis, Depends(get_redis)]


@router.post(
    "/payment-methods",
    response_model=PaymentMethodSetupResponse,
    dependencies=[Depends(require_step_up_after(require_role("operator")))],
)
async def create_payment_method_setup(
    operator: OperatorUser,
    _: KycVerifiedUser,
    db: DatabaseSession,
    payload: PaymentMethodSetupRequest | None = None,
) -> PaymentMethodSetupResponse:
    """Start provider-hosted setup for an Operator payment method.

    Requires an open step-up window. The body carries no fields; it is
    declared only so stray fields such as a raw card number are rejected.
    """
    del payload
    return await service.create_payment_method_setup(db=db, operator=operator)


@router.get("/payment-methods", response_model=PaymentMethodsResponse)
async def list_payment_methods(
    operator: OperatorUser,
    db: DatabaseSession,
) -> PaymentMethodsResponse:
    """List safe metadata for the Operator's provider-held payment methods."""
    return await service.list_payment_methods(db=db, operator=operator)


@router.get("/purchases", response_model=PurchaseHistoryResponse)
async def list_framework_purchases(
    operator: OperatorUser,
    db: DatabaseSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PurchaseHistoryResponse:
    """List the authenticated Operator's Framework purchase history."""
    return await service.list_framework_purchases(
        db=db,
        operator=operator,
        page=page,
        page_size=page_size,
    )


@router.delete(
    "/payment-methods/{payment_method_id}",
    response_model=PaymentMethodDeleteResponse,
    dependencies=[Depends(require_step_up_after(require_role("operator")))],
)
async def delete_payment_method(
    payment_method_id: str,
    operator: OperatorUser,
    db: DatabaseSession,
    payload: PaymentMethodDeleteRequest | None = None,
) -> PaymentMethodDeleteResponse:
    """Remove a provider-held payment method for the authenticated Operator.

    Requires an open step-up window. The body carries no fields; it is
    declared only so stray fields are rejected.
    """
    del payload
    return await service.delete_payment_method(
        db=db,
        operator=operator,
        payment_method_id=payment_method_id,
    )


@router.post("/purchase/{framework_id}", response_model=PurchaseResponse)
async def create_framework_purchase(
    framework_id: UUID,
    payload: PurchaseRequest,
    operator: OperatorUser,
    _: KycVerifiedUser,
    db: DatabaseSession,
) -> PurchaseResponse:
    """Start Stripe checkout for a published self-serve Framework license."""
    return await service.create_framework_purchase(
        db=db,
        operator=operator,
        framework_id=framework_id,
        payload=payload,
    )


@router.post("/collections/{collection_id}/purchase", response_model=PurchaseResponse)
async def create_collection_purchase(
    collection_id: UUID,
    payload: PurchaseRequest,
    operator: OperatorUser,
    _: KycVerifiedUser,
    db: DatabaseSession,
) -> PurchaseResponse:
    """Start Stripe checkout for a published Collection bundle."""
    return await collections_service.create_collection_purchase(
        db=db,
        operator=operator,
        collection_id=collection_id,
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
    """Refund an eligible completed Framework or Collection purchase."""
    return await service.refund_framework_purchase(
        db=db,
        operator=operator,
        transaction_id=transaction_id,
    )


@router.get("/purchases/{transaction_id}/invoice")
async def get_framework_purchase_invoice(
    transaction_id: UUID,
    operator: OperatorUser,
    db: DatabaseSession,
) -> Response:
    """Return a presigned invoice PDF URL, or queue invoice generation."""
    return await service.get_framework_purchase_invoice(
        db=db,
        operator=operator,
        transaction_id=transaction_id,
    )


@router.get("/earnings", response_model=EarningsResponse)
async def get_contributor_earnings(
    contributor: ContributorUser,
    db: DatabaseSession,
) -> EarningsResponse:
    """Return refund-safe earnings balances for the Contributor."""
    return await service.get_contributor_earnings(db=db, contributor=contributor)


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


@router.get(
    "/payout-accounts/banks",
    response_model=PayoutBanksResponse,
    summary="List banks available for payout onboarding",
    description=(
        "Returns the banks a Contributor can register a payout account at, "
        "read live from the payment provider. Bank codes change over time, so "
        "clients must not cache or hardcode this list."
    ),
)
async def list_payout_banks(
    _: ContributorUser,
) -> PayoutBanksResponse:
    """List banks available for Contributor payout onboarding."""
    return await service.list_payout_banks()


@router.post(
    "/payout-accounts/resolve",
    response_model=PayoutAccountResolveResponse,
    summary="Check a bank account before registering it",
    description=(
        "Return the name the bank holds for an account number so it can be "
        "confirmed before it becomes a payout destination. A mistyped number "
        "usually belongs to somebody else rather than being invalid, so this "
        "is the only point at which the mistake is visible. Registers "
        "nothing. Rate limited per caller."
    ),
)
async def resolve_payout_account_name(
    payload: PayoutAccountResolveRequest,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    redis: RedisConnection,
) -> PayoutAccountResolveResponse:
    """Name the holder of a bank account without registering it."""
    return await service.resolve_payout_account_name(
        redis=cast(RedisCounter, redis),
        actor_id=contributor.id,
        payload=payload,
    )


@router.get("/payout-accounts", response_model=PayoutAccountsResponse)
async def list_payout_accounts(
    contributor: ContributorUser,
    db: DatabaseSession,
) -> PayoutAccountsResponse:
    """List active payout accounts for the authenticated Contributor."""
    return await service.list_payout_accounts(db=db, contributor=contributor)


@router.post(
    "/payouts",
    response_model=PayoutResponse,
    status_code=201,
    dependencies=[Depends(require_step_up_after(require_role("contributor")))],
)
async def request_payout(
    payload: PayoutRequest,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    db: DatabaseSession,
) -> PayoutResponse:
    """Request payout of available Contributor earnings.

    Requires an open step-up window.
    """
    return await service.request_payout(
        db=db,
        contributor=contributor,
        payload=payload,
    )


@router.get("/payouts", response_model=PayoutsResponse)
async def list_payouts(
    contributor: ContributorUser,
    db: DatabaseSession,
) -> PayoutsResponse:
    """List payout history for the authenticated Contributor."""
    return await service.list_payouts(db=db, contributor=contributor)


@router.delete(
    "/payout-accounts/{payout_account_id}",
    response_model=PayoutAccountDeleteResponse,
    dependencies=[Depends(require_step_up_after(require_role("contributor")))],
)
async def delete_payout_account(
    payout_account_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
    payload: PayoutAccountDeleteRequest | None = None,
) -> PayoutAccountDeleteResponse:
    """Soft-delete an owned payout account.

    Requires an open step-up window. The body carries no fields; it is
    declared only so stray fields are rejected.
    """
    del payload
    return await service.delete_payout_account(
        db=db,
        contributor=contributor,
        payout_account_id=payout_account_id,
    )
