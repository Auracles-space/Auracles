"""Auth service layer for registration and email verification."""

from __future__ import annotations

import json
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.rate_limit import RateLimiter, RedisCounter
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.modules.auth.models import User, UserRole
from app.modules.auth.schemas import LoginResponse, RegisterRequest
from app.workers.tasks.notifications import send_verification_email

VERIFY_EMAIL_PREFIX = "ev_"
VERIFY_EMAIL_TTL_SECONDS = 86_400
RESEND_VERIFICATION_LIMITER = RateLimiter(
    namespace="resend_verification",
    limit=3,
    window=3_600,
)
LOGIN_IP_LIMITER = RateLimiter(namespace="login_ip", limit=20, window=60)
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECONDS = 900
REFRESH_TOKEN_TTL_SECONDS = 2_592_000


def normalize_email(email: str) -> str:
    """Normalize email addresses before persistence and lookup."""
    return email.strip().lower()


def _verification_key(token: str) -> str:
    """Build the Redis lookup key for a verification token."""
    return f"email_verify:{hash_token(token)}"


def _refresh_key(token: str) -> str:
    """Build the Redis lookup key for a refresh token."""
    return f"refresh:{hash_token(token)}"


def _used_refresh_key(token: str) -> str:
    """Build the Redis replay-detection key for a used refresh token."""
    return f"refresh_used:{hash_token(token)}"


def _family_key(family_id: str) -> str:
    """Build the Redis set key tracking a refresh-token family."""
    return f"refresh_family:{family_id}"


def _login_failure_key(email: str) -> str:
    """Build the Redis failed-login counter key."""
    return f"login_failure:{email}"


async def _load_active_roles(db: AsyncSession, user_id: UUID) -> list[str]:
    """Load roles that should be encoded into access tokens."""
    rows = (
        await db.execute(
            select(UserRole.role, UserRole.approved_at).where(
                UserRole.user_id == user_id
            )
        )
    ).all()
    return [
        role
        for role, approved_at in rows
        if role != "attestor" or approved_at is not None
    ]


async def _store_refresh_token(
    redis: Redis,
    token: str,
    user_id: UUID,
    family_id: str,
    ip: str | None,
    ua: str | None,
) -> None:
    """Store refresh-token metadata and index it by family."""
    now = datetime.now(UTC).isoformat()
    key = _refresh_key(token)
    record = {
        "user_id": str(user_id),
        "family_id": family_id,
        "issued_at": now,
        "last_seen": now,
        "ip": ip,
        "user_agent": ua,
    }
    await redis.setex(key, REFRESH_TOKEN_TTL_SECONDS, json.dumps(record))
    await cast(Awaitable[int], redis.sadd(_family_key(family_id), key))
    await redis.expire(_family_key(family_id), REFRESH_TOKEN_TTL_SECONDS)


async def _revoke_family(redis: Redis, family_id: str) -> None:
    """Delete every refresh token in a replay-suspect family."""
    family_key = _family_key(family_id)
    members = await cast(Awaitable[set[Any]], redis.smembers(family_key))
    keys = [str(member) for member in members]
    if keys:
        await redis.delete(*keys)
    await redis.delete(family_key)


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


async def login(
    db: AsyncSession,
    redis: Redis,
    email: str,
    password: str,
    ip: str | None = None,
    ua: str | None = None,
) -> tuple[LoginResponse, str]:
    """Authenticate a verified user and issue access plus refresh tokens."""
    normalized_email = normalize_email(email)
    await LOGIN_IP_LIMITER.check(cast(RedisCounter, redis), ip or "unknown")
    failure_key = _login_failure_key(normalized_email)
    if int(await redis.get(failure_key) or "0") >= LOGIN_FAILURE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts.",
        )

    user = await db.scalar(select(User).where(User.email == normalized_email))
    if (
        user is None
        or user.password_hash is None
        or not verify_password(password, user.password_hash)
    ):
        attempts = await redis.incr(failure_key)
        if attempts == 1 or await redis.ttl(failure_key) < 0:
            await redis.expire(failure_key, LOGIN_FAILURE_WINDOW_SECONDS)
        await write_audit(
            db=db,
            actor_id=user.id if user else None,
            action="login_failure",
            target_type="user",
            target_id=user.id if user else None,
            metadata={"reason": "invalid_credentials"},
            ip=ip,
            ua=ua,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in.",
        )
    if user.deactivated_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )

    roles = await _load_active_roles(db, user.id)
    access_token = create_access_token(user_id=user.id, roles=roles)
    refresh_token = generate_opaque_token()
    family_id = str(uuid4())
    await _store_refresh_token(redis, refresh_token, user.id, family_id, ip, ua)
    await redis.delete(failure_key)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="login_success",
        target_type="user",
        target_id=user.id,
        ip=ip,
        ua=ua,
    )
    await db.commit()
    return LoginResponse(access_token=access_token), refresh_token


async def refresh(
    db: AsyncSession,
    redis: Redis,
    token: str | None,
    ip: str | None = None,
    ua: str | None = None,
) -> tuple[LoginResponse, str]:
    """Rotate a refresh token and issue a new access token."""
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token.",
        )

    key = _refresh_key(token)
    raw_record = await redis.get(key)
    if raw_record is None:
        used_family_id = await redis.get(_used_refresh_key(token))
        if used_family_id is not None:
            await _revoke_family(redis, str(used_family_id))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token.",
        )

    record = json.loads(raw_record)
    user_id = UUID(record["user_id"])
    family_id = str(record["family_id"])
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None or user.deactivated_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token.",
        )

    roles = await _load_active_roles(db, user.id)
    access_token = create_access_token(user_id=user.id, roles=roles)
    new_refresh_token = generate_opaque_token()
    await redis.delete(key)
    await cast(Awaitable[int], redis.srem(_family_key(family_id), key))
    await redis.setex(_used_refresh_key(token), REFRESH_TOKEN_TTL_SECONDS, family_id)
    await _store_refresh_token(redis, new_refresh_token, user.id, family_id, ip, ua)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="token_refresh",
        target_type="user",
        target_id=user.id,
        ip=ip,
        ua=ua,
    )
    await db.commit()
    return LoginResponse(access_token=access_token), new_refresh_token


async def logout(
    db: AsyncSession,
    redis: Redis,
    token: str | None,
) -> None:
    """Revoke the current refresh token if one was provided."""
    if token is None:
        return
    key = _refresh_key(token)
    raw_record = await redis.get(key)
    if raw_record is not None:
        record = json.loads(raw_record)
        await cast(
            Awaitable[int],
            redis.srem(_family_key(str(record["family_id"])), key),
        )
        await write_audit(
            db=db,
            actor_id=UUID(record["user_id"]),
            action="logout",
            target_type="user",
            target_id=UUID(record["user_id"]),
        )
        await db.commit()
    await redis.delete(key)


async def add_self_role(
    db: AsyncSession,
    user: User,
    role: str,
) -> UserRole:
    """Let a user add Contributor or Operator role to their account."""
    if role == "attestor":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Attestor role requires admin approval.",
        )
    if role not in {"contributor", "operator"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported role.",
        )

    existing = await db.scalar(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role == role)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Role already assigned.",
        )

    assigned_role = UserRole(
        user_id=user.id,
        role=role,
        approved_at=datetime.now(UTC),
    )
    db.add(assigned_role)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="role_assigned",
        target_type="user",
        target_id=user.id,
        metadata={"role": role, "self_assigned": True},
    )
    await db.commit()
    return assigned_role
