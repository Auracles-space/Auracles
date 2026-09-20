"""Celery Beat tasks for saved-search alert digests.

The dispatcher scans alert-enabled saved searches, reuses the canonical Explore
query builder, writes in-app notification rows, queues email digests for
verified users, and advances each cursor only after delivery state is recorded.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from loguru import logger
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.modules.auth.models import User, UserRole
from app.modules.explore import service as explore_service
from app.modules.explore.schemas import ExploreSearchFilters
from app.modules.frameworks.models import Framework
from app.modules.notifications import preferences as notification_preferences
from app.modules.notifications import service as notification_service
from app.modules.saved_searches.models import (
    SavedSearch,
    SavedSearchAlertDelivery,
)
from app.workers.async_runner import run_async
from app.workers.celery_app import app
from app.workers.tasks.notifications import send_saved_search_alert_email

ALERT_BATCH_SIZE = 50


def _framework_link(framework_id: UUID) -> str:
    """Return the public Explore detail link for one Framework."""
    return f"/explore/{framework_id}"


def _saved_search_link(saved_search_id: UUID) -> str:
    """Return the settings link that opens on one saved search.

    There is no per-search detail page, so the link addresses the list and
    names the search in the query string; the panel highlights that row. It
    used to address `/settings/saved-searches/{id}`, which 404ed.
    """
    return f"/settings/saved-searches?highlight={saved_search_id}"


def _cursor_predicate(saved_search: SavedSearch) -> Any:
    """Return the published_at/id cursor predicate for one saved search."""
    if (
        saved_search.last_alerted_at is not None
        and saved_search.last_alerted_framework_id is not None
    ):
        return or_(
            Framework.published_at > saved_search.last_alerted_at,
            and_(
                Framework.published_at == saved_search.last_alerted_at,
                Framework.id > saved_search.last_alerted_framework_id,
            ),
        )
    return Framework.published_at > saved_search.created_at


async def _matching_frameworks(
    db: AsyncSession,
    *,
    saved_search: SavedSearch,
    user_id: UUID,
) -> list[Framework]:
    """Return the next capped batch of undelivered Framework matches."""
    filters = ExploreSearchFilters.model_validate(saved_search.filters)
    delivered = (
        select(SavedSearchAlertDelivery.id)
        .where(
            SavedSearchAlertDelivery.saved_search_id == saved_search.id,
            SavedSearchAlertDelivery.framework_id == Framework.id,
        )
        .limit(1)
    )
    query = (
        explore_service.build_explore_query(
            current_user_id=user_id,
            filters=filters,
        )
        .where(Framework.published_at.is_not(None), _cursor_predicate(saved_search))
        .where(~exists(delivered))
        .order_by(Framework.published_at.asc(), Framework.id.asc())
        .limit(ALERT_BATCH_SIZE)
    )
    rows = await db.execute(query)
    return list(rows.scalars().all())


async def _alert_enabled_searches(
    db: AsyncSession,
) -> list[tuple[SavedSearch, User]]:
    """Load alert-enabled searches whose owners are active Operators."""
    rows = await db.execute(
        select(SavedSearch, User)
        .join(User, User.id == SavedSearch.user_id)
        .join(UserRole, UserRole.user_id == User.id)
        .where(
            SavedSearch.alert_enabled.is_(True),
            User.deactivated_at.is_(None),
            UserRole.role == "operator",
            UserRole.approved_at.is_not(None),
        )
        .order_by(SavedSearch.created_at.asc(), SavedSearch.id.asc())
    )
    return cast("list[tuple[SavedSearch, User]]", list(rows.all()))


async def _send_saved_search_alert(
    db: AsyncSession,
    *,
    saved_search: SavedSearch,
    user: User,
    matches: list[Framework],
) -> None:
    """Persist alert delivery state and queue user-facing digest delivery."""
    final_framework = matches[-1]
    final_published_at = final_framework.published_at
    if final_published_at is None:
        raise ValueError("Saved-search alert match missing published_at.")
    match_payload = [
        {
            "framework_id": str(framework.id),
            "title": framework.title,
            "link": _framework_link(framework.id),
        }
        for framework in matches
    ]
    dedupe_key = f"saved-search-alert:{saved_search.id}:{final_framework.id}"
    title_suffix = "es" if len(matches) != 1 else ""
    in_app_enabled = await notification_preferences.should_deliver(
        db=db,
        user_id=user.id,
        notification_type="saved_search_alert",
        channel="in_app",
    )
    email_enabled = await notification_preferences.should_deliver(
        db=db,
        user_id=user.id,
        notification_type="saved_search_alert",
        channel="email",
    )
    notification = None
    if in_app_enabled:
        notification = await notification_service.create_notification(
            db=db,
            user_id=user.id,
            notification_type="saved_search_alert",
            title=f"{len(matches)} new saved-search match{title_suffix}",
            body=f"New Frameworks match your saved search: {saved_search.name}.",
            link=_saved_search_link(saved_search.id),
            payload={
                "saved_search_id": str(saved_search.id),
                "matches": match_payload,
            },
            dedupe_key=dedupe_key,
        )
    if email_enabled and user.email_verified:
        send_saved_search_alert_email.delay(
            email=user.email,
            saved_search_name=saved_search.name,
            matches=match_payload,
            link=_saved_search_link(saved_search.id),
        )
    for framework in matches:
        db.add(
            SavedSearchAlertDelivery(
                saved_search_id=saved_search.id,
                framework_id=framework.id,
            )
        )
    saved_search.last_alerted_at = final_published_at
    saved_search.last_alerted_framework_id = final_framework.id
    await write_audit(
        db=db,
        actor_id=user.id,
        action="saved_search_alert_sent",
        target_type="saved_search",
        target_id=saved_search.id,
        metadata={
            "match_count": len(matches),
            "notification_id": str(notification.id) if notification else None,
        },
    )


async def _dispatch_saved_search_alerts() -> dict[str, int]:
    """Scan alert-enabled saved searches and send digest notifications."""
    processed_count = 0
    sent_count = 0
    match_count = 0
    async with async_session_factory() as db:
        for saved_search, user in await _alert_enabled_searches(db):
            processed_count += 1
            matches = await _matching_frameworks(
                db,
                saved_search=saved_search,
                user_id=user.id,
            )
            if not matches:
                continue
            if db.in_transaction():
                await db.commit()
            async with db.begin():
                # Refresh inside the write transaction so concurrent Beat workers
                # see a locked, current cursor before delivery rows are inserted.
                locked_search = await db.scalar(
                    select(SavedSearch)
                    .where(SavedSearch.id == saved_search.id)
                    .with_for_update()
                )
                if locked_search is None:
                    continue
                fresh_matches = await _matching_frameworks(
                    db,
                    saved_search=locked_search,
                    user_id=user.id,
                )
                if not fresh_matches:
                    continue
                await _send_saved_search_alert(
                    db,
                    saved_search=locked_search,
                    user=user,
                    matches=fresh_matches,
                )
                sent_count += 1
                match_count += len(fresh_matches)
    return {
        "processed_count": processed_count,
        "sent_count": sent_count,
        "match_count": match_count,
    }


@app.task(bind=True)  # type: ignore[untyped-decorator]
def dispatch_saved_search_alerts(self: Any) -> dict[str, int]:
    """Celery wrapper for periodic saved-search alert digest dispatch."""
    log = logger.bind(
        module="saved_searches",
        action="dispatch_saved_search_alerts",
        task_id=self.request.id,
    )
    log.info("task_started")
    result = run_async(_dispatch_saved_search_alerts())
    log.info("task_completed", result=result)
    return result
