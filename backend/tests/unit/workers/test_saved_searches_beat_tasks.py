"""Tests for Phase 5b-2 saved-search alert Beat tasks.

The Beat task is the money-free but trust-sensitive path that turns saved
Explore filters into digest notifications. These tests exercise the Celery task
boundary with real database rows so cursor, dedupe, and eligibility behavior
remain stable through refactors.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
from app.modules.frameworks.models import Framework
from app.modules.notifications.models import Notification
from app.modules.saved_searches.models import (
    SavedSearch,
    SavedSearchAlertDelivery,
)
from app.shared.models.audit_log import AuditLog
from app.workers.beat_schedule import BEAT_SCHEDULE
from app.workers.tasks import saved_searches_beat


class FakeSavedSearchEmailTask:
    """Celery-task-shaped test double for saved-search digest emails."""

    def __init__(self) -> None:
        """Create empty delayed call storage."""
        self.calls: list[dict[str, Any]] = []

    def delay(self, **kwargs: Any) -> None:
        """Capture one queued saved-search digest email."""
        self.calls.append(kwargs)


def test_saved_search_alert_task_is_registered_in_beat_schedule() -> None:
    """Celery Beat includes the daily saved-search alert dispatcher."""
    schedule = BEAT_SCHEDULE["dispatch-saved-search-alerts-daily"]

    assert schedule["task"] == (
        "app.workers.tasks.saved_searches_beat.dispatch_saved_search_alerts"
    )
    assert schedule["schedule"] == 86400.0


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure saved-search and notification tables exist for Beat task tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def saved_search_beat_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, Any]]:
    """Reset saved-search Beat rows and capture digest email dispatch."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    fake_email_task = FakeSavedSearchEmailTask()

    def cleanup() -> None:
        """Delete rows in dependency order so FK constraints stay satisfied."""
        with session_factory() as session:
            session.execute(delete(AuditLog))
            session.execute(delete(Notification))
            session.execute(delete(SavedSearchAlertDelivery))
            session.execute(delete(SavedSearch))
            session.execute(delete(Framework))
            session.execute(delete(UserRole))
            session.execute(delete(User))
            session.commit()

    cleanup()
    monkeypatch.setattr(
        saved_searches_beat,
        "send_saved_search_alert_email",
        fake_email_task,
    )
    try:
        yield {"session_factory": session_factory, "email_task": fake_email_task}
    finally:
        cleanup()
        sync_engine.dispose()


def create_user(
    session_factory: sessionmaker,
    *,
    email: str,
    email_verified: bool = True,
    roles: list[str] | None = None,
    deactivated_at: datetime | None = None,
) -> UUID:
    """Create a test user with optional roles for saved-search Beat tests."""
    with session_factory() as session:
        user = User(
            email=email,
            password_hash=hash_password("CorrectHorse9"),
            display_name=email.split("@")[0],
            email_verified=email_verified,
            kyc_status="verified",
            deactivated_at=deactivated_at,
        )
        session.add(user)
        session.flush()
        for role in roles or ["operator"]:
            session.add(
                UserRole(
                    user_id=user.id,
                    role=role,
                    approved_at=datetime.now(UTC),
                )
            )
        session.commit()
        return user.id


def create_framework(
    session_factory: sessionmaker,
    contributor_id: UUID,
    *,
    title: str,
    published_at: datetime,
    status: str = "published",
    function: str = "risk_management",
) -> UUID:
    """Create a Framework that may match a saved-search alert."""
    with session_factory() as session:
        framework = Framework(
            contributor_id=contributor_id,
            title=title,
            description=f"{title} implementation package.",
            status=status,
            category="playbook",
            sector="financial_services",
            industry="fund_management",
            business_function=function,
            tags=["risk", "alert"],
            tags_text="risk alert",
            jurisdiction="us",
            complexity=3,
            org_size="mid_market",
            lifecycle_stage="scale",
            price=Decimal("450.00"),
            currency="USD",
            license_types=["single_user", "team"],
            published_at=published_at if status == "published" else None,
        )
        session.add(framework)
        session.commit()
        return framework.id


def create_saved_search(
    session_factory: sessionmaker,
    user_id: UUID,
    *,
    created_at: datetime,
    filters: dict[str, Any] | None = None,
    alert_enabled: bool = True,
) -> UUID:
    """Create an alert-enabled saved search fixture."""
    with session_factory() as session:
        saved_search = SavedSearch(
            user_id=user_id,
            name=f"Alert search {uuid4()}",
            filters=filters
            or {
                "q": "risk",
                "category": "playbook",
                "function": "risk_management",
                "sort": "newest",
            },
            alert_enabled=alert_enabled,
            created_at=created_at,
            updated_at=created_at,
        )
        session.add(saved_search)
        session.commit()
        return saved_search.id


def test_dispatch_saved_search_alerts_sends_digest_and_advances_cursor(
    migrated_database: None,
    saved_search_beat_context: dict[str, Any],
) -> None:
    """A matching published Framework creates one digest and advances cursor."""
    session_factory = saved_search_beat_context["session_factory"]
    contributor_id = create_user(
        session_factory,
        email="alert-contributor@auracles.space",
        roles=["contributor"],
    )
    operator_id = create_user(session_factory, email="alert-operator@auracles.space")
    created_at = datetime.now(UTC) - timedelta(hours=3)
    saved_search_id = create_saved_search(
        session_factory,
        operator_id,
        created_at=created_at,
    )
    old_framework_id = create_framework(
        session_factory,
        contributor_id,
        title="Old Risk Playbook",
        published_at=created_at - timedelta(minutes=1),
    )
    matching_framework_id = create_framework(
        session_factory,
        contributor_id,
        title="New Risk Playbook",
        published_at=created_at + timedelta(minutes=10),
    )

    result = saved_searches_beat.dispatch_saved_search_alerts.apply().get()

    with session_factory() as session:
        saved_search = session.get(SavedSearch, saved_search_id)
        notifications = session.scalars(select(Notification)).all()
        deliveries = session.scalars(select(SavedSearchAlertDelivery)).all()
        audit = session.scalar(
            select(AuditLog).where(AuditLog.action == "saved_search_alert_sent")
        )

    assert result == {"processed_count": 1, "sent_count": 1, "match_count": 1}
    assert saved_search is not None
    assert saved_search.last_alerted_framework_id == matching_framework_id
    assert saved_search.last_alerted_at is not None
    assert len(notifications) == 1
    assert notifications[0].notification_type == "saved_search_alert"
    assert notifications[0].dedupe_key == (
        f"saved-search-alert:{saved_search_id}:{matching_framework_id}"
    )
    assert len(deliveries) == 1
    assert deliveries[0].framework_id == matching_framework_id
    assert deliveries[0].framework_id != old_framework_id
    assert audit is not None
    assert audit.target_id == saved_search_id
    assert len(saved_search_beat_context["email_task"].calls) == 1
    assert saved_search_beat_context["email_task"].calls[0]["matches"] == [
        {
            "framework_id": str(matching_framework_id),
            "title": "New Risk Playbook",
            "link": f"/explore/{matching_framework_id}",
        }
    ]


def test_dispatch_saved_search_alerts_no_match_keeps_cursor_quiet(
    migrated_database: None,
    saved_search_beat_context: dict[str, Any],
) -> None:
    """A quiet period sends nothing and leaves the saved-search cursor unchanged."""
    session_factory = saved_search_beat_context["session_factory"]
    operator_id = create_user(
        session_factory,
        email="alert-no-match@auracles.space",
    )
    saved_search_id = create_saved_search(
        session_factory,
        operator_id,
        created_at=datetime.now(UTC) - timedelta(hours=1),
        filters={"q": "no-matching-framework", "sort": "newest"},
    )

    result = saved_searches_beat.dispatch_saved_search_alerts.apply().get()

    with session_factory() as session:
        saved_search = session.get(SavedSearch, saved_search_id)
        notification_count = len(session.scalars(select(Notification)).all())
        delivery_count = len(session.scalars(select(SavedSearchAlertDelivery)).all())

    assert result == {"processed_count": 1, "sent_count": 0, "match_count": 0}
    assert saved_search is not None
    assert saved_search.last_alerted_at is None
    assert saved_search.last_alerted_framework_id is None
    assert notification_count == 0
    assert delivery_count == 0
    assert saved_search_beat_context["email_task"].calls == []


def test_dispatch_saved_search_alerts_caps_batches_and_dedupes_deliveries(
    migrated_database: None,
    saved_search_beat_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capped broad alerts resume on the next run and never redeliver rows."""
    session_factory = saved_search_beat_context["session_factory"]
    monkeypatch.setattr(saved_searches_beat, "ALERT_BATCH_SIZE", 2)
    contributor_id = create_user(
        session_factory,
        email="alert-cap-contributor@auracles.space",
        roles=["contributor"],
    )
    operator_id = create_user(session_factory, email="alert-cap@auracles.space")
    created_at = datetime.now(UTC) - timedelta(hours=4)
    saved_search_id = create_saved_search(
        session_factory,
        operator_id,
        created_at=created_at,
        filters={"q": "batch", "sort": "newest"},
    )
    framework_ids = [
        create_framework(
            session_factory,
            contributor_id,
            title=f"Batch Risk Playbook {index}",
            published_at=created_at + timedelta(minutes=index),
        )
        for index in range(1, 4)
    ]

    first = saved_searches_beat.dispatch_saved_search_alerts.apply().get()
    second = saved_searches_beat.dispatch_saved_search_alerts.apply().get()
    third = saved_searches_beat.dispatch_saved_search_alerts.apply().get()

    with session_factory() as session:
        delivered_ids = [
            delivery.framework_id
            for delivery in session.scalars(
                select(SavedSearchAlertDelivery).order_by(
                    SavedSearchAlertDelivery.delivered_at.asc(),
                    SavedSearchAlertDelivery.framework_id.asc(),
                )
            )
        ]
        notifications = session.scalars(select(Notification)).all()
        saved_search = session.get(SavedSearch, saved_search_id)

    assert first == {"processed_count": 1, "sent_count": 1, "match_count": 2}
    assert second == {"processed_count": 1, "sent_count": 1, "match_count": 1}
    assert third == {"processed_count": 1, "sent_count": 0, "match_count": 0}
    assert set(delivered_ids) == set(framework_ids)
    assert len(notifications) == 2
    assert len(saved_search_beat_context["email_task"].calls) == 2
    assert saved_search is not None
    assert saved_search.last_alerted_framework_id == framework_ids[-1]


def test_dispatch_saved_search_alerts_skips_inactive_and_unverified_email_users(
    migrated_database: None,
    saved_search_beat_context: dict[str, Any],
) -> None:
    """Inactive users are skipped; unverified email users get only in-app alerts."""
    session_factory = saved_search_beat_context["session_factory"]
    contributor_id = create_user(
        session_factory,
        email="alert-eligibility-contributor@auracles.space",
        roles=["contributor"],
    )
    created_at = datetime.now(UTC) - timedelta(hours=2)
    inactive_id = create_user(
        session_factory,
        email="alert-inactive@auracles.space",
        deactivated_at=datetime.now(UTC),
    )
    unverified_id = create_user(
        session_factory,
        email="alert-unverified@auracles.space",
        email_verified=False,
    )
    no_operator_id = create_user(
        session_factory,
        email="alert-no-role@auracles.space",
        roles=["contributor"],
    )
    inactive_search_id = create_saved_search(
        session_factory,
        inactive_id,
        created_at=created_at,
    )
    unverified_search_id = create_saved_search(
        session_factory,
        unverified_id,
        created_at=created_at,
    )
    no_operator_search_id = create_saved_search(
        session_factory,
        no_operator_id,
        created_at=created_at,
    )
    matching_framework_id = create_framework(
        session_factory,
        contributor_id,
        title="Eligibility Risk Playbook",
        published_at=created_at + timedelta(minutes=5),
    )

    result = saved_searches_beat.dispatch_saved_search_alerts.apply().get()

    with session_factory() as session:
        notifications = session.scalars(select(Notification)).all()
        deliveries = session.scalars(select(SavedSearchAlertDelivery)).all()
        inactive_search = session.get(SavedSearch, inactive_search_id)
        unverified_search = session.get(SavedSearch, unverified_search_id)
        no_operator_search = session.get(SavedSearch, no_operator_search_id)

    assert result == {"processed_count": 1, "sent_count": 1, "match_count": 1}
    assert len(notifications) == 1
    assert notifications[0].user_id == unverified_id
    assert len(deliveries) == 1
    assert deliveries[0].saved_search_id == unverified_search_id
    assert deliveries[0].framework_id == matching_framework_id
    assert inactive_search is not None
    assert inactive_search.last_alerted_at is None
    assert no_operator_search is not None
    assert no_operator_search.last_alerted_at is None
    assert unverified_search is not None
    assert unverified_search.last_alerted_framework_id == matching_framework_id
    assert saved_search_beat_context["email_task"].calls == []
