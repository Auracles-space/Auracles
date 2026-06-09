"""Financials API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.core.redis import get_redis
from app.modules.auth.models import User
from app.modules.financials import service
from app.modules.financials.schemas import (
    PaymentMethodDeleteRequest,
    PaymentMethodDeleteResponse,
    PaymentMethodSetupRequest,
    PaymentMethodSetupResponse,
    PaymentMethodsResponse,
)

router = APIRouter(prefix="/financials", tags=["Financials"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
OperatorUser = Annotated[User, Depends(require_role("operator"))]


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
