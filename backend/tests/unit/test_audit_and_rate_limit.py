"""Behavior tests for audit persistence and Redis-backed rate limits."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, select

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.rate_limit import RateLimiter
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Small Redis test double for fixed-window counter behavior."""

    def __init__(self) -> None:
        """Create empty in-memory Redis-like storage."""
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        """Increment a counter and return the new value."""
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> None:
        """Record the requested TTL for the key."""
        self.expirations[key] = seconds

    async def ttl(self, key: str) -> int:
        """Return the recorded TTL or Redis' no-expiry sentinel."""
        return self.expirations.get(key, -1)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the auth/audit tables exist for persistence tests."""
    engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        engine.dispose()


async def test_write_audit_persists_queryable_security_event(
    migrated_database: None,
) -> None:
    """Audit helper writes a row that can be queried by later settings flows."""
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await write_audit(
            db=session,
            actor_id=None,
            action="login_failure",
            target_type="user",
            metadata={"reason": "bad_password"},
            ip="127.0.0.1",
            ua="pytest",
        )
        await session.commit()

        result = await session.execute(select(AuditLog))
        audit_log = result.scalar_one()

    assert audit_log.action == "login_failure"
    assert audit_log.metadata_ == {"reason": "bad_password"}
    assert str(audit_log.ip_address) == "127.0.0.1"
    assert audit_log.user_agent == "pytest"


async def test_rate_limiter_allows_until_limit_then_raises_429() -> None:
    """Rate limiter raises HTTP 429 only after the configured window is exhausted."""
    redis = FakeRedis()
    limiter = RateLimiter(namespace="login_ip", limit=2, window=60)

    await limiter.check(redis, "127.0.0.1")
    await limiter.check(redis, "127.0.0.1")

    with pytest.raises(HTTPException) as exc_info:
        await limiter.check(redis, "127.0.0.1")

    assert exc_info.value.status_code == 429
    assert redis.expirations["rate_limit:login_ip:127.0.0.1"] == 60


async def test_rate_limiter_429_reports_retry_minutes_and_header() -> None:
    """A minute-scale window surfaces a human wait time and a Retry-After header."""
    redis = FakeRedis()
    limiter = RateLimiter(namespace="login_ip", limit=1, window=60)

    await limiter.check(redis, "1.1.1.1")
    with pytest.raises(HTTPException) as exc_info:
        await limiter.check(redis, "1.1.1.1")

    error = exc_info.value
    assert "1 minute" in error.detail
    assert error.headers is not None
    assert error.headers["Retry-After"] == "60"


async def test_rate_limiter_429_reports_retry_seconds() -> None:
    """A sub-minute window is phrased in seconds, not minutes."""
    redis = FakeRedis()
    limiter = RateLimiter(namespace="forgot_password", limit=1, window=30)

    await limiter.check(redis, "user@example.com")
    with pytest.raises(HTTPException) as exc_info:
        await limiter.check(redis, "user@example.com")

    error = exc_info.value
    assert "30 seconds" in error.detail
    assert error.headers["Retry-After"] == "30"


async def test_rate_limiter_sets_expiry_when_counter_has_no_ttl() -> None:
    """Rate limiter repairs counters that somehow exist without expiration."""
    redis = FakeRedis()
    redis.values["rate_limit:forgot_password:email@example.com"] = 1
    limiter = RateLimiter(namespace="forgot_password", limit=3, window=300)

    await limiter.check(redis, "email@example.com")

    assert redis.expirations["rate_limit:forgot_password:email@example.com"] == 300
