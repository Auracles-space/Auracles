"""The shared async engine pool must not survive a closed event loop.

A pooled asyncpg connection whose loop has gone is unusable, and
``pool_pre_ping`` turns using one into a `RuntimeError` about a Future
"attached to a different loop" in whichever module happens to run next. The
helper under test is what `_isolate_test_module` in conftest calls to make that
impossible; this pins the behaviour so removing the call fails here rather than
as an unrelated module going red on CI.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.core.database import async_session_factory, engine
from tests.support.engine_pool import dispose_shared_async_engine


def test_dispose_empties_a_pool_left_behind_by_a_closed_loop() -> None:
    """A connection returned to the pool on a dead loop does not persist."""

    async def touch() -> None:
        """Check a connection out and back in on a loop that then closes."""
        async with async_session_factory() as db:
            await db.execute(text("select 1"))

    dispose_shared_async_engine()
    assert engine.pool.checkedin() == 0

    asyncio.run(touch())
    assert engine.pool.checkedin() == 1

    dispose_shared_async_engine()

    assert engine.pool.checkedin() == 0
