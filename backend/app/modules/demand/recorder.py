"""Queue one unmet-demand record from the Explore search request.

Sits between the router and the Celery task so the router stays thin and so
the identity decision — signed-in user, or rotating anonymous key — lives in
one place rather than in the endpoint signature.

Maps to: FR-SRCH (search), FR-GDPR (erasure).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from loguru import logger

from app.core.network import client_ip
from app.core.redis import get_redis
from app.modules.demand.service import anonymous_searcher_key
from app.workers.tasks.demand import record_search_gap_task

# The salt lives in Redis and expires, so yesterday's key cannot be recomputed
# even with the application secret. Two days of headroom keeps a search made
# just before midnight comparable with one made just after.
_SALT_TTL_SECONDS = 60 * 60 * 48


async def _daily_salt(now: datetime) -> str:
    """Return today's anonymous-dedupe salt, creating it on first use.

    Args:
        now: Current time, used to derive the day key.

    Returns:
        The day's salt. A fresh random salt is stored if none exists yet.
    """
    redis = get_redis()
    key = f"demand:salt:{now.date().isoformat()}"
    salt = await redis.get(key)
    if salt:
        return str(salt)
    candidate = secrets.token_urlsafe(32)
    # NX so concurrent requests agree on whichever salt landed first.
    await redis.set(key, candidate, ex=_SALT_TTL_SECONDS, nx=True)
    stored = await redis.get(key)
    return str(stored or candidate)


async def queue_search_gap(
    *,
    request: Request,
    query: str | None,
    filters: dict[str, Any],
    searcher_id: UUID | None,
) -> None:
    """Queue one zero-result search for recording.

    Never raises. A demand record is worth having, but not at the cost of the
    search request that produced it, so a failure here is logged and dropped.

    Args:
        request: The incoming search request, for client IP and user-agent.
        query: Free-text query as typed, or None for a filters-only search.
        filters: Filters that were set, already stripped of unset values.
        searcher_id: The signed-in Operator, when there is one.
    """
    try:
        searcher_key: str | None = None
        if searcher_id is None:
            salt = await _daily_salt(datetime.now(UTC))
            searcher_key = anonymous_searcher_key(
                salt=salt,
                ip=client_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
        record_search_gap_task.delay(
            query=query,
            filters=filters,
            searcher_id=str(searcher_id) if searcher_id else None,
            searcher_key=searcher_key,
        )
    except Exception as exc:  # noqa: BLE001 - analytics must not break search
        logger.bind(module="demand", action="queue_search_gap").warning(
            "queue_failed", error=str(exc)
        )
