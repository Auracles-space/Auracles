"""Integration tests for in-app notification endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.notifications.models import Notification


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure notification tables exist for endpoint tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def notifications_context() -> AsyncIterator[dict[str, Any]]:
    """Reset notification/auth rows between endpoint tests."""
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(Notification))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()
    try:
        yield {}
    finally:
        async with async_session_factory() as session:
            await session.execute(delete(Notification))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()
        await engine.dispose()


async def create_user(email: str, roles: list[str]) -> UUID:
    """Create a verified test user with approved roles."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            for role in roles:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        approved_at=datetime.now(UTC),
                    )
                )
        return user.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def create_notification(
    *,
    user_id: UUID,
    notification_type: str = "proposal_accepted",
    title: str = "Proposal accepted",
    body: str = "Your proposal was accepted.",
    read: bool = False,
) -> UUID:
    """Insert a notification row for endpoint assertions."""
    async with async_session_factory() as session:
        async with session.begin():
            notification = Notification(
                user_id=user_id,
                notification_type=notification_type,
                title=title,
                body=body,
                link="/projects/example",
                payload={"project_id": "example"},
                read_at=datetime.now(UTC) if read else None,
            )
            session.add(notification)
            await session.flush()
            return notification.id


async def test_user_lists_and_reads_only_own_notifications(
    client: AsyncClient,
    migrated_database: None,
    notifications_context: dict[str, Any],
) -> None:
    """Notification endpoints are authenticated and scoped to current user."""
    user_id = await create_user("notify@auracles.space", ["operator"])
    other_user_id = await create_user("other-notify@auracles.space", ["operator"])
    unread_id = await create_notification(user_id=user_id)
    await create_notification(user_id=user_id, title="Already read", read=True)
    other_notification_id = await create_notification(user_id=other_user_id)
    headers = auth_headers(user_id, ["operator"])

    listed = await client.get("/v1/notifications", headers=headers)
    unread_only = await client.get(
        "/v1/notifications",
        params={"unread_only": "true"},
        headers=headers,
    )
    marked = await client.patch(f"/v1/notifications/{unread_id}/read", headers=headers)
    other_marked = await client.patch(
        f"/v1/notifications/{other_notification_id}/read",
        headers=headers,
    )

    assert listed.status_code == 200
    assert listed.json()["unread_count"] == 1
    listed_ids = {item["id"] for item in listed.json()["notifications"]}
    assert len(listed_ids) == 2
    assert str(unread_id) in listed_ids
    assert str(other_notification_id) not in listed_ids
    assert unread_only.status_code == 200
    assert [item["id"] for item in unread_only.json()["notifications"]] == [
        str(unread_id)
    ]
    assert marked.status_code == 200
    assert marked.json()["read_at"] is not None
    assert other_marked.status_code == 404

    async with async_session_factory() as session:
        notification = await session.scalar(
            select(Notification).where(Notification.id == unread_id)
        )

    assert notification is not None
    assert notification.read_at is not None


@pytest.mark.parametrize(
    "notification_type",
    ["attestation_clarification_requested", "attestation_clarification_answered"],
)
async def test_clarification_notification_types_persist(
    client: AsyncClient,
    migrated_database: None,
    notifications_context: dict[str, Any],
    notification_type: str,
) -> None:
    """Clarification notification labels must be storable and listable.

    The attestor-to-requestor question and the requestor's answer each raise a
    durable notification typed by ``notification_type_enum``. If the enum omits
    the label the worker insert fails and the recipient's bell stays empty, so
    both labels must round-trip through the notifications table and endpoint.
    """
    user_id = await create_user("clarify@auracles.space", ["operator"])
    notification_id = await create_notification(
        user_id=user_id,
        notification_type=notification_type,
        title="Clarification update",
        body="A clarification changed.",
    )

    listed = await client.get(
        "/v1/notifications", headers=auth_headers(user_id, ["operator"])
    )

    assert listed.status_code == 200
    listed_ids = {item["id"] for item in listed.json()["notifications"]}
    assert str(notification_id) in listed_ids


async def test_user_can_mark_all_own_notifications_read(
    client: AsyncClient,
    migrated_database: None,
    notifications_context: dict[str, Any],
) -> None:
    """Read-all updates only unread notifications owned by the current user."""
    user_id = await create_user("read-all@auracles.space", ["contributor"])
    other_user_id = await create_user("read-all-other@auracles.space", ["operator"])
    await create_notification(user_id=user_id, title="First")
    await create_notification(user_id=user_id, title="Second")
    other_id = await create_notification(user_id=other_user_id, title="Other")

    response = await client.post(
        "/v1/notifications/read-all",
        headers=auth_headers(user_id, ["contributor"]),
    )

    async with async_session_factory() as session:
        own_unread = (
            (
                await session.execute(
                    select(Notification).where(
                        Notification.user_id == user_id,
                        Notification.read_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        other_notification = await session.scalar(
            select(Notification).where(Notification.id == other_id)
        )

    assert response.status_code == 200
    assert response.json() == {"updated_count": 2}
    assert own_unread == []
    assert other_notification is not None
    assert other_notification.read_at is None
