"""Async execution helper for synchronous Celery worker tasks.

Celery task functions are synchronous, while the Auracles backend uses async
SQLAlchemy sessions. This helper keeps a reusable event loop per worker thread
so pooled asyncpg connections stay attached to a stable loop across tasks.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any

_thread_state = threading.local()


def _worker_loop() -> asyncio.AbstractEventLoop:
    """Return the reusable event loop for the current worker thread."""
    loop = getattr(_thread_state, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _thread_state.loop = loop
    return loop


def run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Run an async worker implementation from a synchronous Celery task."""
    loop = _worker_loop()
    if loop.is_running():
        raise RuntimeError("Worker event loop is already running")
    return loop.run_until_complete(coroutine)
