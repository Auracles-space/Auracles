"""Health check service.

Pings the database and Redis concurrently, returning per-component
readiness without leaking connection strings or internal error detail.
The API component is implicitly OK if this code is executing.
"""

import asyncio

import redis.asyncio as redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import async_session_factory


async def _check_database() -> dict[str, str]:
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        return {"status": "unavailable", "detail": "database ping failed"}

    return {"status": "ok"}


async def _check_redis() -> dict[str, str]:
    settings = get_settings()
    client = redis.from_url(  # type: ignore[no-untyped-call]
        settings.cache_redis_url, encoding="utf-8"
    )
    try:
        await client.ping()
    except Exception:
        return {"status": "unavailable", "detail": "redis ping failed"}
    finally:
        await client.aclose()

    return {"status": "ok"}


async def run_health_checks() -> dict[str, dict[str, str]]:
    """Check required platform components without exposing connection details."""
    database, cache = await asyncio.gather(_check_database(), _check_redis())
    return {
        "api": {"status": "ok"},
        "database": database,
        "redis": cache,
    }
