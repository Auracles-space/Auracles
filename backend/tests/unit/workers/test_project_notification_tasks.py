"""Tests for project notification Celery dispatch."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.auth.models import User, UserRole
from app.modules.notifications.models import Notification
from app.workers.tasks import project_notifications


class FakeProjectEmailTask:
    """Celery-task-shaped test double for project notification emails."""

    def __init__(self) -> None:
        """Create empty delayed call storage."""
        self.calls: list[dict[str, Any]] = []

    def delay(self, **kwargs: Any) -> None:
        """Capture a queued project notification email."""
        self.calls.append(kwargs)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure notification tables exist for worker tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def project_notification_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, Any]]:
    """Reset notification rows and capture realtime/email dispatch."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    published: list[dict[str, Any]] = []
    fake_email_task = FakeProjectEmailTask()

    async def fake_publish_to_channel(
        channel: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Capture realtime publishes without requiring Redis."""
        published.append(
            {"channel": channel, "event_type": event_type, "payload": payload}
        )

    def cleanup() -> None:
        """Delete notifications and users in dependency order."""
        with session_factory() as session:
            session.execute(delete(Notification))
            session.execute(delete(UserRole))
            session.execute(delete(User))
            session.commit()

    cleanup()
    monkeypatch.setattr(
        project_notifications,
        "publish_to_channel",
        fake_publish_to_channel,
    )
    monkeypatch.setattr(
        project_notifications,
        "send_project_notification_email",
        fake_email_task,
    )
    try:
        yield {"published": published, "email_task": fake_email_task}
    finally:
        cleanup()
        sync_engine.dispose()


def create_user(email: str) -> UUID:
    """Create a test user for notification dispatch."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        user = User(
            email=email,
            password_hash=hash_password("CorrectHorse9"),
            display_name=email.split("@")[0],
            email_verified=True,
        )
        session.add(user)
        session.flush()
        session.add(
            UserRole(
                user_id=user.id,
                role="operator",
                approved_at=datetime.now(UTC),
            )
        )
        session.commit()
        user_id = user.id
    sync_engine.dispose()
    return user_id


def test_dispatch_project_notification_dedupes_and_fans_out(
    migrated_database: None,
    project_notification_context: dict[str, Any],
) -> None:
    """Dispatcher inserts once, publishes once, and queues email once per dedupe key."""
    user_id = create_user("project-notify@auracles.space")
    project_id = str(uuid4())

    first = project_notifications.dispatch_project_notification.apply(
        kwargs={
            "user_id": str(user_id),
            "notification_type": "proposal_accepted",
            "title": "Proposal accepted",
            "body": "Your proposal was accepted.",
            "payload": {"project_id": project_id},
            "link": f"/projects/{project_id}",
            "dedupe_key": f"proposal_accepted:{project_id}",
        }
    ).get()
    duplicate = project_notifications.dispatch_project_notification.apply(
        kwargs={
            "user_id": str(user_id),
            "notification_type": "proposal_accepted",
            "title": "Proposal accepted",
            "body": "Your proposal was accepted.",
            "payload": {"project_id": project_id},
            "link": f"/projects/{project_id}",
            "dedupe_key": f"proposal_accepted:{project_id}",
        }
    ).get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        notification_count = session.scalar(select(func.count(Notification.id)))
    sync_engine.dispose()

    assert first["status"] == "dispatched"
    assert duplicate["status"] == "duplicate"
    assert notification_count == 1
    assert len(project_notification_context["published"]) == 1
    assert project_notification_context["published"][0]["channel"] == f"user:{user_id}"
    assert len(project_notification_context["email_task"].calls) == 1


def test_dispatch_project_notification_without_dedupe_key_always_inserts(
    migrated_database: None,
    project_notification_context: dict[str, Any],
) -> None:
    """NULL dedupe keys bypass conflict handling and always create rows."""
    user_id = create_user("project-notify-unique@auracles.space")

    for _ in range(2):
        project_notifications.dispatch_project_notification.apply(
            kwargs={
                "user_id": str(user_id),
                "notification_type": "project_created",
                "title": "Project created",
                "body": "A new project notification exists.",
                "payload": None,
                "link": None,
                "dedupe_key": None,
            }
        ).get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        notification_count = session.scalar(select(func.count(Notification.id)))
    sync_engine.dispose()

    assert notification_count == 2
    assert len(project_notification_context["published"]) == 2
    assert len(project_notification_context["email_task"].calls) == 2
