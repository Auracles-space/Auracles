"""Unit tests for recording unmet demand from zero-result Explore searches.

A search that returns nothing is the only search we keep: it is self-evidently
a gap in the catalogue. These tests cover what is written, what is scrubbed out
of it before storage, and how a searcher is identified.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.demand import service as demand_service
from app.modules.demand.models import SearchGap


@pytest.fixture(autouse=True)
async def _clean_gaps() -> None:
    """Empty the gap table before each test.

    Module-level truncation runs once, so without this the second test in the
    file reads the first test's row as well as its own.
    """
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(SearchGap))
        await session.commit()


async def _create_searcher() -> UUID:
    """Create one verified Operator to attribute a search to."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"operator-demand-{uuid4()}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Demand Operator",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            return user.id


async def test_zero_result_search_is_recorded_with_its_terms_and_filters() -> None:
    """A search that found nothing must be stored as a gap.

    The query is kept as normalised terms so the demand map can count words
    across searchers, and the filters are kept verbatim so a filter-only search
    still registers.
    """
    await engine.dispose()
    searcher_id = await _create_searcher()
    async with async_session_factory() as session:
        await demand_service.record_search_gap(
            session,
            query="SOC 2 readiness",
            filters={"sector": "technology", "jurisdiction": "NG"},
            searcher_id=searcher_id,
            searcher_key=None,
            now=datetime.now(UTC),
        )
        await session.commit()

        gap = (await session.execute(select(SearchGap))).scalars().one()

    assert gap.searcher_id == searcher_id
    assert gap.searcher_key is None
    assert gap.query == "SOC 2 readiness"
    assert gap.terms == ["soc", "2", "readiness"]
    assert gap.filters == {"sector": "technology", "jurisdiction": "NG"}


async def test_personal_data_is_scrubbed_out_of_the_stored_query() -> None:
    """An email or phone number typed into the search box must not be stored.

    People do paste a client's contact details into a search box. For an
    anonymous searcher we would hold that with no way to ever honour a deletion
    request against it, so it never reaches the table.
    """
    await engine.dispose()
    async with async_session_factory() as session:
        await demand_service.record_search_gap(
            session,
            query="audit for ada@example.com or +2348012345678",
            filters={},
            searcher_id=None,
            searcher_key="anon-key",
            now=datetime.now(UTC),
        )
        await session.commit()

        gap = (await session.execute(select(SearchGap))).scalars().one()

    assert "ada@example.com" not in gap.query
    assert "2348012345678" not in gap.query
    assert "audit" in gap.query
    assert gap.terms == ["audit"]
