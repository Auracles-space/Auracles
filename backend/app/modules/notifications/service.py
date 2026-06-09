"""Notification service functions.

All public reads and mutations are scoped to the authenticated user. Background
tasks use this module to create durable notification rows before realtime or
email dispatch occurs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.notifications.models import Notification
from app.modules.notifications.schemas import NotificationItem, NotificationsResponse


def _to_item(notification: Notification) -> NotificationItem:
    """Convert an ORM notification row into the public response shape."""
    return NotificationItem(
        id=notification.id,
        type=notification.notification_type,
        title=notification.title,
        body=notification.body,
        link=notification.link,
        payload=notification.payload,
        read_at=notification.read_at,
        created_at=notification.created_at,
    )


def _owned_notifications_query(user_id: UUID) -> Select[tuple[Notification]]:
    """Build the base query for notifications owned by one user."""
    return select(Notification).where(Notification.user_id == user_id)


async def list_notifications(
    *,
    db: AsyncSession,
    user: User,
    page: int,
    page_size: int,
    unread_only: bool,
) -> NotificationsResponse:
    """Return the authenticated user's notifications and unread count."""
    base_query = _owned_notifications_query(user.id)
    filtered_query = base_query
    if unread_only:
        filtered_query = filtered_query.where(Notification.read_at.is_(None))

    total = await db.scalar(select(func.count()).select_from(filtered_query.subquery()))
    unread_count = await db.scalar(
        select(func.count()).select_from(
            base_query.where(Notification.read_at.is_(None)).subquery()
        )
    )
    result = await db.execute(
        filtered_query.order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    return NotificationsResponse(
        notifications=[_to_item(notification) for notification in result.scalars()],
        unread_count=int(unread_count or 0),
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


async def mark_notification_read(
    *,
    db: AsyncSession,
    user: User,
    notification_id: UUID,
) -> NotificationItem:
    """Mark one owned notification as read and return its updated row."""
    notification = await db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await db.commit()
    return _to_item(notification)


async def mark_all_notifications_read(
    *,
    db: AsyncSession,
    user: User,
) -> int:
    """Mark every unread notification owned by the user as read."""
    result = await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


async def create_notification(
    *,
    db: AsyncSession,
    user_id: UUID,
    notification_type: str,
    title: str,
    body: str,
    link: str | None,
    payload: dict[str, Any] | None,
    dedupe_key: str | None,
) -> Notification | None:
    """Create a durable notification row, collapsing duplicate dedupe keys."""
    statement: Any = (
        pg_insert(Notification)
        .values(
            user_id=user_id,
            type=notification_type,
            title=title,
            body=body,
            link=link,
            payload=payload,
            dedupe_key=dedupe_key,
        )
        .returning(Notification.id)
    )

    if dedupe_key is not None:
        statement = statement.on_conflict_do_nothing(
            index_elements=["user_id", "dedupe_key"],
            index_where=Notification.dedupe_key.is_not(None),
        )

    notification_id = await db.scalar(statement)
    if notification_id is None:
        return None
    return await db.get(Notification, notification_id)
