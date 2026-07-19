"""Tests for admin-review notification fan-out Celery dispatch.

Admins are a role, not a single user, so review-pending events fan out one
durable notification to every account holding the admin role. Non-admin
accounts must never receive these notifications.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.auth.models import User, UserRole
from app.modules.notifications.models import Notification
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import admin_notifications, project_notifications
from tests.support.db_cleanup import clear_identity_state_sync


class FakeProjectEmailTask:
    """Celery-task-shaped test double for project notification emails."""

    def __init__(self) -> None:
        """Create empty delayed call storage."""
        self.calls: list[dict[str, Any]] = []

    def delay(self, **kwargs: Any) -> None:
        """Capture a queued notification email."""
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
def admin_notification_context(
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
            session.execute(delete(AuditLog))
            session.execute(delete(Notification))
            clear_identity_state_sync(session)
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


def create_user(email: str, *, role: str) -> UUID:
    """Create a test user holding one role for fan-out tests."""
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
                role=role,
                approved_at=datetime.now(UTC),
            )
        )
        session.commit()
        user_id = user.id
    sync_engine.dispose()
    return user_id


def test_dispatch_admin_notification_fans_out_to_every_admin(
    migrated_database: None,
    admin_notification_context: dict[str, Any],
) -> None:
    """One review-pending event creates a notification for each admin only."""
    admin_one = create_user("admin-one@auracles.space", role="admin")
    admin_two = create_user("admin-two@auracles.space", role="admin")
    create_user("operator@auracles.space", role="operator")
    target_id = str(uuid4())

    result = admin_notifications.dispatch_admin_notification.apply(
        kwargs={
            "notification_type": "admin_review_pending",
            "title": "Developer application submitted",
            "body": "A new Developer application is awaiting review.",
            "payload": {"domain": "developer_application", "target_id": target_id},
            "link": "/admin/developer",
            "dedupe_key": f"admin_review_pending:developer_application:{target_id}",
        }
    ).get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        rows = list(session.scalars(select(Notification)).all())
    sync_engine.dispose()

    recipients = {row.user_id for row in rows}
    assert result["status"] == "dispatched"
    assert result["admin_count"] == 2
    assert recipients == {admin_one, admin_two}
    assert all(row.notification_type == "admin_review_pending" for row in rows)


def test_dispatch_admin_notification_dedupes_per_admin(
    migrated_database: None,
    admin_notification_context: dict[str, Any],
) -> None:
    """Re-firing the same review event must not duplicate per-admin rows."""
    create_user("admin-dedupe@auracles.space", role="admin")
    target_id = str(uuid4())
    kwargs = {
        "notification_type": "admin_review_pending",
        "title": "Credential submitted",
        "body": "A credential is awaiting verification.",
        "payload": {"domain": "credential", "target_id": target_id},
        "link": "/admin/credentials",
        "dedupe_key": f"admin_review_pending:credential:{target_id}",
    }

    admin_notifications.dispatch_admin_notification.apply(kwargs=kwargs).get()
    admin_notifications.dispatch_admin_notification.apply(kwargs=kwargs).get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        count = len(list(session.scalars(select(Notification)).all()))
    sync_engine.dispose()

    assert count == 1
