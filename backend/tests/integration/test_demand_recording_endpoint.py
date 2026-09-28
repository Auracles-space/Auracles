"""Integration tests for recording demand from the public Explore search.

Only a search that returns nothing is recorded. A search that found something
is not a gap, and recording it would mean holding personal data that answers no
question anyone asked.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import hash_password
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework


@pytest.fixture(autouse=True)
def _fresh_redis() -> None:
    """Drop the cached Redis client so it binds to this test's event loop.

    The recorder swallows a Redis failure by design — search must never break
    for analytics — so a stale client makes this test silently assert nothing.
    """
    get_redis.cache_clear()


async def _cleanup() -> None:
    """Remove seeded catalog rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(Framework))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()


async def _seed_published_framework(title: str) -> None:
    """Publish one Framework so a matching search returns a result."""
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            contributor = User(
                email=f"contributor-demand-{uuid4()}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Demand Contributor",
                email_verified=True,
            )
            session.add(contributor)
            await session.flush()
            session.add(
                UserRole(
                    user_id=contributor.id,
                    role="contributor",
                    approved_at=now - timedelta(days=1),
                )
            )
            session.add(
                Framework(
                    contributor_id=contributor.id,
                    title=title,
                    description="A published Framework for demand tests.",
                    status="published",
                    category="operations",
                    sector="technology",
                    industry="software",
                    business_function="operations",
                    tags=["demand"],
                    tags_text="demand",
                    price=Decimal("100.00"),
                    currency="USD",
                    license_types=["single_user"],
                    pipeline_failure_reasons={},
                    published_at=now - timedelta(hours=1),
                )
            )


async def test_a_search_that_finds_nothing_is_recorded_as_demand(
    client: AsyncClient,
) -> None:
    """A zero-result search must be queued for recording, with its filters.

    The searcher is anonymous here, so it carries a rotating key rather than a
    user id — that key is what lets the demand map count distinct people
    without holding a record of anyone.
    """
    await engine.dispose()
    await _cleanup()
    try:
        with patch("app.modules.demand.recorder.record_search_gap_task") as task:
            response = await client.get(
                "/v1/explore/frameworks",
                params={"q": "soc 2 readiness", "sector": "technology"},
            )
    finally:
        await _cleanup()
        await engine.dispose()

    assert response.status_code == 200
    assert response.json()["total"] == 0
    task.delay.assert_called_once()
    kwargs = task.delay.call_args.kwargs
    assert kwargs["query"] == "soc 2 readiness"
    assert kwargs["filters"] == {"sector": "technology"}
    assert kwargs["searcher_id"] is None
    assert kwargs["searcher_key"]


async def test_a_search_that_finds_something_is_not_recorded(
    client: AsyncClient,
) -> None:
    """A search with results is not a gap, so nothing about it is stored."""
    await engine.dispose()
    await _cleanup()
    try:
        await _seed_published_framework("Incident Response Playbook")
        with patch("app.modules.demand.recorder.record_search_gap_task") as task:
            response = await client.get(
                "/v1/explore/frameworks",
                params={"q": "incident response"},
            )
    finally:
        await _cleanup()
        await engine.dispose()

    assert response.status_code == 200
    assert response.json()["total"] == 1
    task.delay.assert_not_called()
