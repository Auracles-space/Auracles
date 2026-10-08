"""Shared async engine pool isolation for the test suite.

The application's async SQLAlchemy engine is a module-level singleton, so its
connection pool outlives any one event loop. A test that drives the app through
``asyncio.run`` or ``TestClient`` returns its asyncpg connections to that pool
when its loop closes, and the next module to check one out gets a connection
bound to a loop that no longer exists.

With ``pool_pre_ping`` enabled, the checkout runs a ping on that dead
connection and raises ``RuntimeError: ... got Future ... attached to a
different loop`` — which is what took the realtime WebSocket gateway tests red
on CI while every local ordering passed. Which module runs before which is
decided by how xdist distributes files, so it cannot be left to ordering.
"""

from __future__ import annotations

import asyncio

from app.core.database import engine


def dispose_shared_async_engine() -> None:
    """Empty the shared async engine's pool from synchronous test code.

    Runs the async dispose on a throwaway loop so pooled asyncpg connections
    are closed properly rather than dropped, which would leak the sockets and
    emit "coroutine was never awaited" noise for the rest of the session.
    """
    asyncio.run(engine.dispose())
