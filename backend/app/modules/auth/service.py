"""Auth service layer for registration and email verification."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.rate_limit import RateLimiter, RedisCounter
from app.core.security import generate_opaque_token, hash_password, hash_token
from app.modules.auth.models import User, UserRole
from app.modules.auth.schemas import RegisterRequest
from app.workers.tasks.notifications import send_verification_email

VERIFY_EMAIL_PREFIX = "ev_"
VERIFY_EMAIL_TTL_SECONDS = 86_400
RESEND_VERIFICATION_LIMITER = RateLimiter(
    namespace="resend_verification",
    limit=3,
    window=3_600,
)


def normalize_email(email: str) -> str:
    """Normalize email addresses before persistence and lookup."""
    return email.strip().lower()


def _verification_key(token: str) -> str:
    """Build the Redis lookup key for a verification token."""
    return f"email_verify:{hash_token(token)}"


async def register_user(
    db: AsyncSession,
    redis: Redis,
    request: RegisterRequest,
    ip: str | None = None,
    ua: str | None = None,
) -> None:
    """Register a user and dispatch an email verification token."""
    email = normalize_email(str(request.email))
    log = logger.bind(module="auth", action="register_user")

    user = User(
        email=email,
        password_hash=hash_password(request.password.get_secret_value()),
        display_name=request.display_name.strip(),
    )

    try:
        async with db.begin():
            db.add(user)
            await db.flush()
            for role in request.roles:
                db.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        approved_at=None if role == "attestor" else datetime.now(UTC),
                    )
                )
            await write_audit(
                db=db,
                actor_id=user.id,
                action="register_success",
                target_type="user",
                target_id=user.id,
                metadata={"roles": list(request.roles)},
                ip=ip,
                ua=ua,
            )
    except IntegrityError:
        await db.rollback()
        log.info("register_duplicate_attempt", email=email)
        await write_audit(
            db=db,
            actor_id=None,
            action="register_duplicate_attempt",
            target_type="user",
            metadata={"email": email},
            ip=ip,
            ua=ua,
        )
        await db.commit()
        return

    token = f"{VERIFY_EMAIL_PREFIX}{generate_opaque_token()}"
    await redis.setex(_verification_key(token), VERIFY_EMAIL_TTL_SECONDS, str(user.id))
    send_verification_email.delay(email, token)
    log.bind(user_id=user.id).info("register_success")


async def verify_email(
    db: AsyncSession,
    redis: Redis,
    token: str,
    ip: str | None = None,
    ua: str | None = None,
) -> None:
    """Verify an email address using a Redis-backed one-time token."""
    if not token.startswith(VERIFY_EMAIL_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification token.",
        )

    key = _verification_key(token)
    user_id = await redis.get(key)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Verification token expired or already used.",
        )

    parsed_user_id = UUID(str(user_id))
    async with db.begin():
        user = await db.scalar(select(User).where(User.id == parsed_user_id))
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification token.",
            )
        user.email_verified = True
        await write_audit(
            db=db,
            actor_id=user.id,
            action="email_verified",
            target_type="user",
            target_id=user.id,
            ip=ip,
            ua=ua,
        )

    await redis.delete(key)


async def resend_verification(
    db: AsyncSession,
    redis: Redis,
    email: str,
) -> None:
    """Resend verification when the user exists and remains unverified."""
    normalized_email = normalize_email(email)
    await RESEND_VERIFICATION_LIMITER.check(cast(RedisCounter, redis), normalized_email)
    user = await db.scalar(select(User).where(User.email == normalized_email))
    if user is None or user.email_verified:
        return

    token = f"{VERIFY_EMAIL_PREFIX}{generate_opaque_token()}"
    await redis.setex(_verification_key(token), VERIFY_EMAIL_TTL_SECONDS, str(user.id))
    send_verification_email.delay(normalized_email, token)
