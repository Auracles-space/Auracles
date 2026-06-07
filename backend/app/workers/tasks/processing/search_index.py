"""Search-index refresh step for Framework catalog discovery.

The current schema uses a Postgres expression GIN index rather than a stored
`tsvector` column. Refreshing the search index therefore means syncing the
plain-text fields that feed that expression, especially `tags_text`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger

from app.core.database import async_session_factory
from app.modules.frameworks.models import Framework
from app.workers.async_runner import run_async
from app.workers.celery_app import app


def tags_to_search_text(tags: list[str]) -> str:
    """Convert Framework tags into stable text consumed by Postgres FTS."""
    return " ".join(tag.strip() for tag in tags if tag.strip())


async def _refresh_framework_tsvector_impl(framework_id: str) -> dict[str, Any]:
    """Refresh the Framework fields used by the FTS expression index."""
    parsed_framework_id = UUID(framework_id)
    async with async_session_factory() as db:
        framework = await db.get(Framework, parsed_framework_id)
        if framework is None:
            return {"framework_id": framework_id, "status": "missing"}

        framework.tags_text = tags_to_search_text(framework.tags)
        await db.commit()

    return {
        "framework_id": framework_id,
        "status": "search_index_refreshed",
    }


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def refresh_framework_tsvector(self: Any, framework_id: str) -> dict[str, Any]:
    """Celery wrapper for Framework search-index refresh."""
    log = logger.bind(
        module="artifacts",
        action="refresh_framework_tsvector",
        task_id=self.request.id,
        framework_id=framework_id,
    )
    log.info("task_started")
    try:
        result = run_async(_refresh_framework_tsvector_impl(framework_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
