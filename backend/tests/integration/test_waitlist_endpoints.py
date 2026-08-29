"""Integration tests for the public marketing waitlist endpoint.

Exercise the unauthenticated `POST /v1/waitlist` API that collects pre-launch
interest emails. Verifies normalization, deduplication (the same address never
creates a second row), and validation through HTTP rather than service internals.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, func, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.main import app
from app.modules.waitlist.models import WaitlistEntry


class FakeRedis:
    """In-memory Redis double for fixed-window rate limiting."""

    async def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool:
        """Store a string value, optionally respecting NX semantics."""
        del ex
        store = self.__dict__.setdefault("values", {})
        if nx and key in store:
            return False
        store[key] = value
        return True

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a string value with a TTL (test double ignores expiry)."""
        del seconds
        self.__dict__.setdefault("values", {})[key] = value

    def __init__(self) -> None:
        """Create empty counter and expiry state."""
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        """Increment and return an integer counter."""
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> bool:
        """Record a key expiry request."""
        self.expirations[key] = seconds
        return True

    async def ttl(self, key: str) -> int:
        """Return a positive TTL so the limiter never repairs in tests."""
        return self.expirations.get(key, -1)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the waitlist table exists for these endpoint tests."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def waitlist_context() -> AsyncIterator[dict[str, Any]]:
    """Reset waitlist rows and install a fake Redis for rate limiting."""
    fake_redis = FakeRedis()
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(WaitlistEntry))
            await session.commit()

    await cleanup()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield {"redis": fake_redis}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def _count_entries() -> int:
    async with async_session_factory() as session:
        return await session.scalar(select(func.count()).select_from(WaitlistEntry))


@pytest.mark.usefixtures("migrated_database", "waitlist_context")
async def test_join_waitlist_records_email(client: AsyncClient) -> None:
    """A first-time email is stored and reported as newly added."""
    response = await client.post(
        "/v1/waitlist", json={"email": "Founder@Example.com", "source": "hero"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["already_joined"] is False

    async with async_session_factory() as session:
        entry = await session.scalar(select(WaitlistEntry))
    # Email is normalized to lowercase regardless of submitted casing.
    assert entry is not None
    assert entry.email == "founder@example.com"
    assert entry.source == "hero"


@pytest.mark.usefixtures("migrated_database", "waitlist_context")
async def test_join_waitlist_deduplicates_email(client: AsyncClient) -> None:
    """Re-submitting the same address never creates a second row."""
    first = await client.post("/v1/waitlist", json={"email": "dup@example.com"})
    assert first.status_code == 201
    assert first.json()["already_joined"] is False

    # Different casing + surrounding whitespace must collapse to the same entry.
    second = await client.post("/v1/waitlist", json={"email": " DUP@example.com "})
    assert second.status_code == 200
    assert second.json()["already_joined"] is True

    assert await _count_entries() == 1


@pytest.mark.usefixtures("migrated_database", "waitlist_context")
async def test_join_waitlist_rejects_malformed_email(client: AsyncClient) -> None:
    """A malformed email is rejected by validation, storing nothing."""
    response = await client.post("/v1/waitlist", json={"email": "not-an-email"})

    assert response.status_code == 422
    assert await _count_entries() == 0
