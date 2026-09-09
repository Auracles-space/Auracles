"""Redis fixed-window rate limiting utilities.

Endpoints use this small helper to protect auth-sensitive paths without
coupling router code to Redis command details.
"""

import math
from typing import Protocol

from fastapi import HTTPException, status


def format_retry_phrase(seconds: int) -> str:
    """Render a wait duration as a short, user-facing phrase.

    Sub-minute waits are reported in seconds; longer waits are rounded up to
    whole minutes so the message never tells a user to retry "in 0 minutes".

    Shared with the auth lockouts, which count failures themselves rather than
    going through ``RateLimiter`` but owe the user the same answer.

    Args:
        seconds: Remaining cooldown in seconds.

    Returns:
        A phrase like ``"30 seconds"`` or ``"2 minutes"``.
    """
    if seconds < 60:
        unit = "second" if seconds == 1 else "seconds"
        return f"{seconds} {unit}"
    minutes = math.ceil(seconds / 60)
    unit = "minute" if minutes == 1 else "minutes"
    return f"{minutes} {unit}"


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
            # Tell the user exactly how long to wait. A negative TTL means the
            # key has no expiry recorded yet, so fall back to the full window.
            ttl = await redis.ttl(redis_key)
            retry_after = ttl if ttl > 0 else self.window
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "Too many attempts. Please try again in "
                    f"{format_retry_phrase(retry_after)}."
                ),
                headers={"Retry-After": str(retry_after)},
            )
