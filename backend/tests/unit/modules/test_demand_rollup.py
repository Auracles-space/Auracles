"""Unit tests for rolling raw search gaps into permanent demand counts.

The rollup is what lets demand outlive the people who expressed it: it counts
distinct searchers per term and per filter combination, and the counted rows
carry no identity at all.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.demand import service as demand_service
from app.modules.demand.models import DemandSignal, SearchGap

PERIOD = date(2026, 9, 1)


@pytest.fixture(autouse=True)
async def _clean() -> None:
    """Empty both demand tables before each test."""
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(DemandSignal))
        await session.execute(delete(SearchGap))
        await session.commit()


async def _searcher() -> UUID:
    """Create one signed-in searcher."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"searcher-{uuid4()}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Searcher",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            return user.id


async def _gap(
    *,
    query: str,
    filters: dict[str, str] | None = None,
    searcher_id: UUID | None = None,
    searcher_key: str | None = None,
    when: datetime,
) -> None:
    """Record one gap directly."""
    async with async_session_factory() as session:
        await demand_service.record_search_gap(
            session,
            query=query,
            filters=filters or {},
            searcher_id=searcher_id,
            searcher_key=searcher_key,
            now=when,
        )
        await session.commit()


async def test_rollup_counts_distinct_searchers_not_searches() -> None:
    """One person searching repeatedly must count once, not many times.

    The aggregation floor is a promise about how many *people* wanted
    something. Counting rows instead of searchers would let one determined
    visitor manufacture demand.
    """
    when = datetime(2026, 9, 15, tzinfo=UTC)
    keen = await _searcher()
    for _ in range(5):
        await _gap(query="soc 2 readiness", searcher_id=keen, when=when)
    await _gap(query="soc 2 audit", searcher_key="anon-a", when=when)

    async with async_session_factory() as session:
        await demand_service.roll_up_demand(session, period=PERIOD)
        await session.commit()
        rows = {
            row.term: row.searcher_count
            for row in (await session.execute(select(DemandSignal))).scalars()
            if row.term
        }

    assert rows["soc"] == 2
    assert rows["readiness"] == 1
    assert rows["audit"] == 1


async def test_rollup_counts_filter_combinations_separately() -> None:
    """A filters-only search registers demand even with no words typed."""
    when = datetime(2026, 9, 10, tzinfo=UTC)
    for key in ("anon-a", "anon-b"):
        await _gap(
            query="",
            filters={"sector": "financial services", "jurisdiction": "NG"},
            searcher_key=key,
            when=when,
        )

    async with async_session_factory() as session:
        await demand_service.roll_up_demand(session, period=PERIOD)
        await session.commit()
        rows = [
            row
            for row in (await session.execute(select(DemandSignal))).scalars()
            if not row.term
        ]

    assert len(rows) == 1
    assert rows[0].searcher_count == 2
    assert rows[0].filters == {"sector": "financial services", "jurisdiction": "NG"}


async def test_rollup_is_idempotent_across_reruns() -> None:
    """Re-running a month must restate its counts, never add to them."""
    when = datetime(2026, 9, 20, tzinfo=UTC)
    await _gap(query="iso 27001", searcher_key="anon-a", when=when)

    async with async_session_factory() as session:
        await demand_service.roll_up_demand(session, period=PERIOD)
        await session.commit()
    await _gap(query="iso 27001", searcher_key="anon-b", when=when)
    async with async_session_factory() as session:
        await demand_service.roll_up_demand(session, period=PERIOD)
        await session.commit()
        rows = {
            row.term: row.searcher_count
            for row in (await session.execute(select(DemandSignal))).scalars()
            if row.term
        }

    assert rows["iso"] == 2
    assert rows["27001"] == 2


async def test_sweep_deletes_raw_rows_past_retention_but_not_the_counts() -> None:
    """Identity expires; demand does not.

    This is the whole point of the two-table split — after the sweep the counts
    still stand and there is no longer a person behind them.
    """
    now = datetime(2026, 9, 30, tzinfo=UTC)
    await _gap(
        query="soc 2",
        searcher_key="anon-old",
        when=now - timedelta(days=120),
    )
    await _gap(query="soc 2", searcher_key="anon-new", when=now - timedelta(days=5))

    async with async_session_factory() as session:
        await demand_service.roll_up_demand(session, period=PERIOD)
        deleted = await demand_service.sweep_expired_gaps(session, now=now)
        await session.commit()
        remaining = (await session.execute(select(SearchGap))).scalars().all()
        counts = (await session.execute(select(DemandSignal))).scalars().all()

    assert deleted == 1
    assert [row.searcher_key for row in remaining] == ["anon-new"]
    assert any(row.term == "soc" for row in counts)
