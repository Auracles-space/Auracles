"""Partner API key authentication and request logging.

The Partner API uses `X-API-Key` instead of browser JWTs. This module verifies
hashed keys, enforces scopes, applies per-key Redis rate limits, emits threshold
notifications, and records API usage logs after responses are produced.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.audit import write_audit
from app.core.database import async_session_factory, get_db
from app.core.redis import get_redis
from app.modules.auth.models import User
from app.modules.developer.models import ApiKey, ApiRequestLog, DeveloperAccount
from app.modules.notifications.preferences import should_deliver
from app.modules.notifications.service import create_notification

RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_WINDOW_MS = RATE_LIMIT_WINDOW_SECONDS * 1000
RATE_LIMIT_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local suffix = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  return {0, count}
end
redis.call('ZADD', key, now, tostring(now) .. ':' .. tostring(count) .. ':' .. suffix)
redis.call('PEXPIRE', key, window)
return {1, count + 1}
"""
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
ApiKeyHeader = Annotated[str | None, Header(alias="X-API-Key")]


@dataclass(frozen=True)
class PartnerApiContext:
    """Authenticated Partner API context injected into Partner routes."""

    api_key: ApiKey
    developer_account: DeveloperAccount


def _hash_api_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest used for API key lookup."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _retry_after_seconds() -> int:
    """Return the retry-after duration for one rate-limit window."""
    return RATE_LIMIT_WINDOW_SECONDS


async def _rate_limit_count(
    redis: Redis,
    api_key_id: UUID,
    limit: int,
) -> tuple[bool, int, int]:
    """Apply the Redis sliding-window limiter and return state."""
    now_ms = int(time.time() * 1000)
    window_bucket = now_ms // RATE_LIMIT_WINDOW_MS
    result = await redis.eval(
        RATE_LIMIT_LUA,
        1,
        f"partner-api-rate:{api_key_id}",
        now_ms,
        RATE_LIMIT_WINDOW_MS,
        limit,
        secrets.token_hex(8),
    )
    allowed = bool(int(result[0]))
    count = int(result[1])
    return allowed, count, window_bucket


async def _notify_rate_limit_threshold_once(
    db: AsyncSession,
    redis: Redis,
    api_key: ApiKey,
    developer_account: DeveloperAccount,
    count: int,
    window_bucket: int,
) -> None:
    """Create one notification per key/window once usage reaches 80%."""
    threshold = math.ceil(api_key.rate_limit_per_min * 0.8)
    if count < threshold:
        return

    throttle_key = f"partner-api-threshold-notified:{api_key.id}:{window_bucket}"
    should_notify = await redis.set(
        throttle_key,
        "1",
        ex=RATE_LIMIT_WINDOW_SECONDS,
        nx=True,
    )
    if not should_notify:
        return

    if not await should_deliver(
        db=db,
        user_id=developer_account.user_id,
        notification_type="api_rate_limit_threshold",
        channel="in_app",
    ):
        return

    await create_notification(
        db=db,
        user_id=developer_account.user_id,
        notification_type="api_rate_limit_threshold",
        title="API key nearing rate limit",
        body=(
            f"{api_key.name} has used {count}/{api_key.rate_limit_per_min} "
            "requests in the current minute."
        ),
        link="/developer/api-keys",
        payload={
            "api_key_id": str(api_key.id),
            "key_prefix": api_key.key_prefix,
            "count": count,
            "limit": api_key.rate_limit_per_min,
        },
        dedupe_key=f"api-rate-threshold:{api_key.id}:{window_bucket}",
    )


async def authenticate_partner_api_key(
    request: Request,
    db: DatabaseSession,
    redis: RedisClient,
    x_api_key: ApiKeyHeader = None,
) -> PartnerApiContext:
    """Authenticate one Partner API request from the `X-API-Key` header."""
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key.",
        )

    result = await db.execute(
        select(ApiKey, DeveloperAccount, User)
        .join(DeveloperAccount, DeveloperAccount.id == ApiKey.developer_account_id)
        .join(User, User.id == DeveloperAccount.user_id)
        .where(ApiKey.key_hash == _hash_api_key(x_api_key))
    )
    row = result.one_or_none()
    if row is None:
        await write_audit(
            db=db,
            actor_id=None,
            action="partner_api_key_invalid",
            target_type="api_key",
            metadata={"key_hash": _hash_api_key(x_api_key)},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )

    api_key, developer_account, user = row
    request.state.partner_api_key_id = api_key.id

    now = datetime.now(UTC)
    if (
        api_key.status != "active"
        or developer_account.status != "active"
        or user.deactivated_at is not None
        or user.suspended_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is not active.",
        )
    if api_key.expires_at is not None and api_key.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key has expired.",
        )

    allowed, count, window_bucket = await _rate_limit_count(
        redis=redis,
        api_key_id=api_key.id,
        limit=api_key.rate_limit_per_min,
    )
    await _notify_rate_limit_threshold_once(
        db=db,
        redis=redis,
        api_key=api_key,
        developer_account=developer_account,
        count=count,
        window_bucket=window_bucket,
    )
    api_key.last_used_at = now
    await db.commit()

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="API key rate limit exceeded.",
            headers={"Retry-After": str(_retry_after_seconds())},
        )

    return PartnerApiContext(api_key=api_key, developer_account=developer_account)


PartnerApiAuth = Annotated[
    PartnerApiContext,
    Depends(authenticate_partner_api_key),
]


def require_api_key_scope(
    required_scope: str,
) -> Callable[[PartnerApiContext], PartnerApiContext]:
    """Build a dependency that enforces one Partner API key scope."""

    async def checker(context: PartnerApiAuth) -> PartnerApiContext:
        """Return Partner API context when the key has the required scope."""
        if required_scope not in context.api_key.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key scope is not allowed for this endpoint.",
            )
        return context

    return checker


class PartnerApiRequestLoggingMiddleware(BaseHTTPMiddleware):
    """Persist per-key Partner API request logs after responses are available."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Record endpoint/status/latency for authenticated API key requests."""
        started_at = time.perf_counter()
        response = await call_next(request)
        api_key_id: UUID | None = getattr(request.state, "partner_api_key_id", None)
        if api_key_id is None:
            return response

        response_ms = int((time.perf_counter() - started_at) * 1000)
        async with async_session_factory() as session:
            async with session.begin():
                session.add(
                    ApiRequestLog(
                        api_key_id=api_key_id,
                        endpoint=request.url.path,
                        method=request.method,
                        status_code=response.status_code,
                        response_ms=response_ms,
                        ip=request.client.host if request.client else None,
                    )
                )
        return response
