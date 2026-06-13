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
from app.modules.notifications.models import Notification, NotificationPreference
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import project_notifications
from tests.support.db_cleanup import clear_identity_state_sync


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


def create_preference(
    *,
    user_id: UUID,
    notification_type: str,
    channel: str,
    enabled: bool,
) -> None:
    """Persist one notification-preference override for worker tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        session.add(
            NotificationPreference(
                user_id=user_id,
                notification_type=notification_type,
                category="project",
                channel=channel,
                enabled=enabled,
            )
        )
        session.commit()
    sync_engine.dispose()


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


def test_dispatch_project_notification_accepts_attestation_types(
    migrated_database: None,
    project_notification_context: dict[str, Any],
) -> None:
    """Dispatcher persists new Attestation notification enum labels."""
    user_id = create_user("attestation-notify@auracles.space")
    attestation_id = str(uuid4())

    result = project_notifications.dispatch_project_notification.apply(
        kwargs={
            "user_id": str(user_id),
            "notification_type": "attestation_fee_funded",
            "title": "Attestation fee funded",
            "body": "Your Attestation fee is now held in escrow.",
            "payload": {"attestation_id": attestation_id},
            "link": f"/attestations/{attestation_id}",
            "dedupe_key": f"attestation_fee_funded:{attestation_id}",
        }
    ).get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        notification = session.scalar(select(Notification))
    sync_engine.dispose()

    assert result["status"] == "dispatched"
    assert notification is not None
    assert notification.notification_type == "attestation_fee_funded"
    assert project_notification_context["published"][0]["channel"] == f"user:{user_id}"


def test_dispatch_project_notification_skips_email_when_email_channel_disabled(
    migrated_database: None,
    project_notification_context: dict[str, Any],
) -> None:
    """Project dispatch keeps in-app delivery when only email is disabled."""
    user_id = create_user("project-no-email@auracles.space")
    create_preference(
        user_id=user_id,
        notification_type="proposal_accepted",
        channel="email",
        enabled=False,
    )

    result = project_notifications.dispatch_project_notification.apply(
        kwargs={
            "user_id": str(user_id),
            "notification_type": "proposal_accepted",
            "title": "Proposal accepted",
            "body": "Your proposal was accepted.",
            "payload": {"project_id": str(uuid4())},
            "link": "/projects/example",
            "dedupe_key": "proposal_accepted:no-email",
        }
    ).get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        notification_count = session.scalar(select(func.count(Notification.id)))
    sync_engine.dispose()

    assert result["status"] == "dispatched"
    assert notification_count == 1
    assert len(project_notification_context["published"]) == 1
    assert project_notification_context["email_task"].calls == []


def test_dispatch_project_notification_skips_in_app_when_in_app_channel_disabled(
    migrated_database: None,
    project_notification_context: dict[str, Any],
) -> None:
    """Project dispatch can send email without creating an in-app notification."""
    user_id = create_user("project-no-bell@auracles.space")
    create_preference(
        user_id=user_id,
        notification_type="proposal_accepted",
        channel="in_app",
        enabled=False,
    )

    result = project_notifications.dispatch_project_notification.apply(
        kwargs={
            "user_id": str(user_id),
            "notification_type": "proposal_accepted",
            "title": "Proposal accepted",
            "body": "Your proposal was accepted.",
            "payload": {"project_id": str(uuid4())},
            "link": "/projects/example",
            "dedupe_key": "proposal_accepted:no-bell",
        }
    ).get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        notification_count = session.scalar(select(func.count(Notification.id)))
    sync_engine.dispose()

    assert result["status"] == "in_app_suppressed"
    assert result["notification_id"] is None
    assert notification_count == 0
    assert project_notification_context["published"] == []
    assert len(project_notification_context["email_task"].calls) == 1


def test_dispatch_project_notification_suppresses_when_both_channels_disabled(
    migrated_database: None,
    project_notification_context: dict[str, Any],
) -> None:
    """Project dispatch returns suppressed when both channels are disabled."""
    user_id = create_user("project-quiet@auracles.space")
    create_preference(
        user_id=user_id,
        notification_type="proposal_accepted",
        channel="in_app",
        enabled=False,
    )
    create_preference(
        user_id=user_id,
        notification_type="proposal_accepted",
        channel="email",
        enabled=False,
    )

    result = project_notifications.dispatch_project_notification.apply(
        kwargs={
            "user_id": str(user_id),
            "notification_type": "proposal_accepted",
            "title": "Proposal accepted",
            "body": "Your proposal was accepted.",
            "payload": {"project_id": str(uuid4())},
            "link": "/projects/example",
            "dedupe_key": "proposal_accepted:quiet",
        }
    ).get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        notification_count = session.scalar(select(func.count(Notification.id)))
    sync_engine.dispose()

    assert result["status"] == "suppressed"
    assert notification_count == 0
    assert project_notification_context["published"] == []
    assert project_notification_context["email_task"].calls == []


def test_dispatch_project_notification_critical_types_bypass_preferences(
    migrated_database: None,
    project_notification_context: dict[str, Any],
) -> None:
    """Critical notification types must ignore stored disabled preferences."""
    user_id = create_user("project-critical@auracles.space")
    create_preference(
        user_id=user_id,
        notification_type="dispute_resolved_release",
        channel="in_app",
        enabled=False,
    )
    create_preference(
        user_id=user_id,
        notification_type="dispute_resolved_release",
        channel="email",
        enabled=False,
    )

    result = project_notifications.dispatch_project_notification.apply(
        kwargs={
            "user_id": str(user_id),
            "notification_type": "dispute_resolved_release",
            "title": "Dispute resolved",
            "body": "Escrow was released after dispute resolution.",
            "payload": {"project_id": str(uuid4())},
            "link": "/projects/example",
            "dedupe_key": "dispute_resolved_release:critical",
        }
    ).get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        notification_count = session.scalar(select(func.count(Notification.id)))
    sync_engine.dispose()

    assert result["status"] == "dispatched"
    assert notification_count == 1
    assert len(project_notification_context["published"]) == 1
    assert len(project_notification_context["email_task"].calls) == 1


def test_dispatch_project_notification_email_only_mode_keeps_deduplication(
    migrated_database: None,
    project_notification_context: dict[str, Any],
) -> None:
    """Email-only delivery with a dedupe key must not queue duplicate emails."""
    user_id = create_user("project-email-dedup@auracles.space")
    create_preference(
        user_id=user_id,
        notification_type="proposal_accepted",
        channel="in_app",
        enabled=False,
    )

    first = project_notifications.dispatch_project_notification.apply(
        kwargs={
            "user_id": str(user_id),
            "notification_type": "proposal_accepted",
            "title": "Proposal accepted",
            "body": "Your proposal was accepted.",
            "payload": {"project_id": str(uuid4())},
            "link": "/projects/example",
            "dedupe_key": "proposal_accepted:email-only-dedup",
        }
    ).get()
    duplicate = project_notifications.dispatch_project_notification.apply(
        kwargs={
            "user_id": str(user_id),
            "notification_type": "proposal_accepted",
            "title": "Proposal accepted",
            "body": "Your proposal was accepted.",
            "payload": {"project_id": str(uuid4())},
            "link": "/projects/example",
            "dedupe_key": "proposal_accepted:email-only-dedup",
        }
    ).get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        notification_count = session.scalar(select(func.count(Notification.id)))
    sync_engine.dispose()

    assert first["status"] == "in_app_suppressed"
    assert duplicate["status"] == "duplicate"
    assert notification_count == 0
    assert project_notification_context["published"] == []
    assert len(project_notification_context["email_task"].calls) == 1
