"""Integration tests for the public demand map endpoint.

Public by decision: a visitor who sees proven unmet demand has a concrete
reason to join and serve it. That makes the aggregation floor load-bearing —
nothing below it may ever reach the response.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.modules.demand.models import DemandSignal, SearchGap


@pytest.fixture(autouse=True)
async def _clean() -> None:
    """Empty demand rows before each test."""
    await engine.dispose()
    # The Redis client is cached per process, so a client built on an earlier
    # test's event loop fails here once that loop is closed.
    get_redis.cache_clear()
    async with async_session_factory() as session:
        await session.execute(delete(DemandSignal))
        await session.execute(delete(SearchGap))
        await session.commit()


async def _signal(
    *,
    term: str = "",
    filters: dict[str, str] | None = None,
    signature: str = "",
    count: int,
    period: date,
) -> None:
    """Insert one pre-counted demand signal."""
    async with async_session_factory() as session:
        session.add(
            DemandSignal(
                period=period,
                term=term,
                filter_signature=signature,
                filters=filters or {},
                searcher_count=count,
            )
        )
        await session.commit()


async def test_demand_map_is_public_and_ranks_terms_by_interest(
    client: AsyncClient,
) -> None:
    """An unauthenticated visitor must be able to read the demand map."""
    this_month = datetime.now(UTC).date().replace(day=1)
    await _signal(term="soc", count=9, period=this_month)
    await _signal(term="iso", count=4, period=this_month)

    response = await client.get("/v1/explore/demand")

    assert response.status_code == 200
    body = response.json()
    assert [row["term"] for row in body["terms"]] == ["soc", "iso"]
    assert body["terms"][0]["searcher_count"] == 9
    assert body["min_searchers"] == 3


async def test_demand_below_the_floor_is_never_returned(
    client: AsyncClient,
) -> None:
    """A term two people searched for must not appear at all.

    This is the whole protection on a public page: below the floor, a term
    starts describing individuals rather than a market.
    """
    this_month = datetime.now(UTC).date().replace(day=1)
    await _signal(term="soc", count=3, period=this_month)
    await _signal(term="aardvark", count=2, period=this_month)

    response = await client.get("/v1/explore/demand")

    assert response.status_code == 200
    terms = [row["term"] for row in response.json()["terms"]]
    assert terms == ["soc"]
    assert "aardvark" not in terms


async def test_filter_combinations_are_returned_alongside_terms(
    client: AsyncClient,
) -> None:
    """A filters-only search registers demand even with no words typed."""
    this_month = datetime.now(UTC).date().replace(day=1)
    await _signal(
        filters={"sector": "financial services"},
        signature="sector=financial services",
        count=6,
        period=this_month,
    )

    response = await client.get("/v1/explore/demand")

    assert response.status_code == 200
    body = response.json()
    assert body["terms"] == []
    assert body["filters"][0]["filters"] == {"sector": "financial services"}
    assert body["filters"][0]["searcher_count"] == 6


async def test_demand_older_than_the_window_is_excluded(
    client: AsyncClient,
) -> None:
    """Demand from two years ago was probably filled; it is not shown."""
    stale = (datetime.now(UTC).date().replace(day=1) - timedelta(days=800)).replace(
        day=1
    )
    await _signal(term="ancient", count=50, period=stale)

    response = await client.get("/v1/explore/demand")

    assert response.status_code == 200
    assert response.json()["terms"] == []
