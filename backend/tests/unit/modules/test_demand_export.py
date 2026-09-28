"""Unit test for including a searcher's own demand rows in their GDPR export.

A recorded search is personal data while it names someone, so right of access
covers it for as long as we hold it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.demand import service as demand_service
from app.modules.demand.models import DemandSignal, SearchGap
from app.modules.gdpr import export_service


@pytest.fixture(autouse=True)
async def _clean() -> None:
    """Empty demand rows before each test."""
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(DemandSignal))
        await session.execute(delete(SearchGap))
        await session.commit()


async def test_export_includes_the_user_s_own_searches_and_nobody_else_s() -> None:
    """The bundle carries this user's recorded searches only."""
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            subject = User(
                email=f"subject-{uuid4()}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Subject",
                email_verified=True,
            )
            other = User(
                email=f"other-{uuid4()}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Other",
                email_verified=True,
            )
            session.add_all([subject, other])
            await session.flush()
            subject_id, other_id = subject.id, other.id

    async with async_session_factory() as session:
        await demand_service.record_search_gap(
            session,
            query="soc 2 readiness",
            filters={"sector": "technology"},
            searcher_id=subject_id,
            searcher_key=None,
            now=now,
        )
        await demand_service.record_search_gap(
            session,
            query="iso 27001",
            filters={},
            searcher_id=other_id,
            searcher_key=None,
            now=now,
        )
        await session.commit()

    async with async_session_factory() as session:
        bundle = await export_service.build_data_export_bundle(
            db=session, user_id=subject_id
        )

    searches = bundle["searches"]
    assert len(searches) == 1
    assert searches[0]["query"] == "soc 2 readiness"
    assert searches[0]["filters"] == {"sector": "technology"}
