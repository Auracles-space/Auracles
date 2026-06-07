"""Redis fixed-window rate limiting utilities.

Endpoints use this small helper to protect auth-sensitive paths without
coupling router code to Redis command details.
"""

from typing import Protocol

from fastapi import HTTPException, status


class RedisCounter(Protocol):
    """Subset of Redis commands required by the rate limiter."""

    async def incr(self, key: str) -> int:
        """Increment a counter and return its value."""

    async def expire(self, key: str, seconds: int) -> object:
        """Set the counter's expiration window."""

    async def ttl(self, key: str) -> int:
        """Return the counter's remaining TTL in seconds."""


class RateLimiter:
    """Fixed-window Redis rate limiter for auth endpoints."""

    def __init__(self, namespace: str, limit: int, window: int) -> None:
        """Configure a limiter namespace, request limit, and window seconds."""
        self.namespace = namespace
        self.limit = limit
        self.window = window

    async def check(self, redis: RedisCounter, key: str) -> None:
        """Raise HTTP 429 when the key exceeds its configured request window."""
        redis_key = f"rate_limit:{self.namespace}:{key}"
        count = await redis.incr(redis_key)

        # New keys and repaired keys must always expire to avoid permanent lockout.
        if count == 1 or await redis.ttl(redis_key) < 0:
            await redis.expire(redis_key, self.window)

        if count > self.limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded.",
            )
