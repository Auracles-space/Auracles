"""Service layer for the pre-launch marketing waitlist.

Encapsulates the single business rule: each normalized email may appear on the
waitlist exactly once. Re-submission is idempotent, never a duplicate or error.
"""

from __future__ import annotations

from typing import Any, cast

from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import RateLimiter, RedisCounter
from app.modules.waitlist.models import WaitlistEntry
from app.modules.waitlist.schemas import WaitlistJoinRequest, WaitlistJoinResponse

# Cap signups per source IP so the public endpoint cannot be flooded.
WAITLIST_IP_LIMITER = RateLimiter(namespace="waitlist_ip", limit=10, window=3600)


def normalize_email(email: str) -> str:
    """Return the canonical lowercase form used for deduplication."""
    return email.strip().lower()


async def join_waitlist(
    *,
    db: AsyncSession,
    redis: Redis,
    request: WaitlistJoinRequest,
    ip: str | None,
) -> WaitlistJoinResponse:
    """Add an email to the waitlist, collapsing duplicates idempotently.

    Rate-limits per source IP, normalizes the email, then inserts with an
    ON CONFLICT DO NOTHING guard so a concurrent or repeat submission of the
    same address never creates a second row or raises.

    Args:
        db: Async database session.
        redis: Redis counter backing the per-IP rate limiter.
        request: Validated join payload (email + optional source).
        ip: Originating client IP, used only as the rate-limit key.

    Returns:
        WaitlistJoinResponse with `already_joined` False on first insert and
        True when the email was already present.
    """
    await WAITLIST_IP_LIMITER.check(cast(RedisCounter, redis), ip or "unknown")

    email = normalize_email(str(request.email))
    log = logger.bind(module="waitlist", action="join_waitlist")

    statement: Any = (
        pg_insert(WaitlistEntry)
        .values(email=email, source=request.source)
        .on_conflict_do_nothing(constraint="uq_waitlist_entries_email")
        .returning(WaitlistEntry.id)
    )
    inserted_id = await db.scalar(statement)
    await db.commit()

    if inserted_id is None:
        log.info("waitlist_join_duplicate")
        return WaitlistJoinResponse(
            already_joined=True,
            message="You're already on the waitlist — we'll be in touch.",
        )

    log.info("waitlist_join_created")
    return WaitlistJoinResponse(
        already_joined=False,
        message="You've been added to the waitlist.",
    )
