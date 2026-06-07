"""Redis client lifecycle helpers.

The application uses Redis for Celery, refresh/session state, rate limiting,
and short-lived auth tokens. This module exposes the app-cache client used by
FastAPI dependencies and services.
"""

from functools import lru_cache
from typing import cast

import redis.asyncio as redis

from app.core.config import get_settings


@lru_cache
def get_redis() -> redis.Redis:
    """Return the cached Redis client for application cache/session usage."""
    settings = get_settings()
    return cast(
        redis.Redis,
        redis.from_url(settings.cache_redis_url, encoding="utf-8"),  # type: ignore[no-untyped-call]
    )


async def close_redis() -> None:
    """Close the cached Redis client during application shutdown."""
    client = get_redis()
    await client.aclose()
    get_redis.cache_clear()
