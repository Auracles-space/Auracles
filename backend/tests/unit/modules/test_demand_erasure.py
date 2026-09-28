"""Unit tests for erasing a searcher's raw demand rows on account deletion.

Demand outlives the person who expressed it, but the row that names them does
not. The counts in `demand_signals` carry no identity and are untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.demand import service as demand_service
from app.modules.demand.models import DemandSignal, SearchGap
from app.modules.gdpr import anonymise
from app.modules.gdpr.models import AccountDeletionRequest


@pytest.fixture(autouse=True)
async def _clean() -> None:
    """Empty demand and deletion-request rows before each test."""
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(DemandSignal))
        await session.execute(delete(SearchGap))
        await session.execute(delete(AccountDeletionRequest))
        await session.commit()


async def test_account_deletion_removes_the_searcher_s_raw_rows_only() -> None:
    """Erasure drops the leaver's search rows and nobody else's.

    The rows cannot simply be nulled: `ck_search_gaps_searcher_xor` requires
    exactly one identity per row, so a row with neither would be invalid. The
    counts they fed are permanent and anonymous, so deleting the raw rows
    costs no demand signal.
    """
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            leaver = User(
                email=f"leaver-{uuid4()}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Leaver",
                email_verified=True,
            )
            stayer = User(
                email=f"stayer-{uuid4()}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Stayer",
                email_verified=True,
            )
            session.add_all([leaver, stayer])
            await session.flush()
            leaver_id = leaver.id
            stayer_id = stayer.id
            request = AccountDeletionRequest(
                user_id=leaver_id,
                status="scheduled",
                scheduled_for=now + timedelta(days=7),
            )
            session.add(request)
            await session.flush()
            request_id = request.id

    async with async_session_factory() as session:
        for searcher_id in (leaver_id, stayer_id):
            await demand_service.record_search_gap(
                session,
                query="soc 2 readiness",
                filters={},
                searcher_id=searcher_id,
                searcher_key=None,
                now=now,
            )
        await demand_service.record_search_gap(
            session,
            query="soc 2 readiness",
            filters={},
            searcher_id=None,
            searcher_key="anon-a",
            now=now,
        )
        await demand_service.roll_up_demand(session, period=now.date())
        await session.commit()

    async with async_session_factory() as session:
        await anonymise.anonymise_user_records(
            db=session,
            user_id=leaver_id,
            request_id=request_id,
            completed_at=now,
        )
        await session.commit()
        remaining = (await session.execute(select(SearchGap))).scalars().all()
        counts = {
            row.term: row.searcher_count
            for row in (await session.execute(select(DemandSignal))).scalars()
            if row.term
        }

    assert sorted(
        str(row.searcher_id) if row.searcher_id else row.searcher_key
        for row in remaining
    ) == sorted(["anon-a", str(stayer_id)])
    # The count still says three people wanted this. It no longer says who.
    assert counts["soc"] == 3
