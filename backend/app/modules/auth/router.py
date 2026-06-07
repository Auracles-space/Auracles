"""FastAPI router for auth registration and verification endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.modules.auth import service
from app.modules.auth.schemas import (
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    VerifyEmailRequest,
)

router = APIRouter(prefix="/auth", tags=["Auth"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]


def _client_ip(request: Request) -> str | None:
    """Return the client IP address when available."""
    return request.client.host if request.client else None


@router.post("/register", response_model=RegisterResponse)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: DatabaseSession,
    redis: RedisClient,
) -> RegisterResponse:
    """Register a user and send an email verification link."""
    await service.register_user(
        db=db,
        redis=redis,
        request=payload,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )
    return RegisterResponse()


@router.post("/verify-email", response_model=RegisterResponse)
async def verify_email(
    payload: VerifyEmailRequest,
    request: Request,
    db: DatabaseSession,
    redis: RedisClient,
) -> RegisterResponse:
    """Verify a user's email address with a one-time token."""
    await service.verify_email(
        db=db,
        redis=redis,
        token=payload.token,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )
    return RegisterResponse(message="Email verified.")


@router.post("/resend-verification", response_model=RegisterResponse)
async def resend_verification(
    payload: ResendVerificationRequest,
    db: DatabaseSession,
    redis: RedisClient,
) -> RegisterResponse:
    """Resend an email verification link without revealing account existence."""
    await service.resend_verification(db=db, redis=redis, email=str(payload.email))
    return RegisterResponse()
