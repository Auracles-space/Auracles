"""Tests for the identity-verification verdict email fanout.

Manual KYC is asynchronous from the user's side: they upload a document and
then have no way of knowing an admin has looked at it. The in-app notification
only helps someone already on the site, so the verdict has to reach them by
email or it effectively does not reach them at all.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.notifications.models import NotificationPreference
from app.workers.tasks import kyc_notifications


class FakeVerdictEmail:
    """Records verdict emails instead of sending them."""

    def __init__(self) -> None:
        """Create empty call storage."""
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> None:
        """Capture one send."""
        self.calls.append(kwargs)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the tables these tests touch exist."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
def verdict_context(
    migrated_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, Any]]:
    """Seed a user and capture the outgoing verdict email."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=sync_engine)
    email = f"kyc-verdict-{uuid4().hex[:8]}@auracles.test"

    with Session() as session:
        user = User(
            email=email,
            password_hash=hash_password("CorrectHorse9"),
            display_name="Verdict Subject",
            email_verified=True,
        )
        session.add(user)
        session.commit()
        user_id = user.id

    sender = FakeVerdictEmail()
    monkeypatch.setattr(kyc_notifications, "send_kyc_verdict_email", sender)

    try:
        yield {"email": email, "sender": sender, "session": Session, "user_id": user_id}
    finally:
        with Session() as session:
            session.execute(
                delete(NotificationPreference).where(
                    NotificationPreference.user_id == user_id
                )
            )
            session.execute(delete(User).where(User.id == user_id))
            session.commit()
        sync_engine.dispose()


def test_verified_verdict_emails_the_user(verdict_context: dict[str, Any]) -> None:
    """An approval reaches the user by email, not only in the app."""
    result = kyc_notifications.send_kyc_verdict_notification.apply(
        kwargs={"user_id": str(verdict_context["user_id"]), "verified": True}
    ).get()

    assert result["status"] == "sent"
    assert verdict_context["sender"].calls == [
        {"email": verdict_context["email"], "verified": True}
    ]


def test_rejected_verdict_emails_the_user(verdict_context: dict[str, Any]) -> None:
    """A rejection reaches the user too — it is the actionable one."""
    kyc_notifications.send_kyc_verdict_notification.apply(
        kwargs={"user_id": str(verdict_context["user_id"]), "verified": False}
    ).get()

    assert verdict_context["sender"].calls == [
        {"email": verdict_context["email"], "verified": False}
    ]


def test_verdict_email_respects_the_account_preference(
    verdict_context: dict[str, Any],
) -> None:
    """A user who turned this email off is not emailed."""
    Session = verdict_context["session"]
    with Session() as session:
        session.add(
            NotificationPreference(
                user_id=verdict_context["user_id"],
                notification_type="kyc_verified",
                category="account",
                channel="email",
                enabled=False,
            )
        )
        session.commit()

    result = kyc_notifications.send_kyc_verdict_notification.apply(
        kwargs={"user_id": str(verdict_context["user_id"]), "verified": True}
    ).get()

    assert result["status"] == "suppressed"
    assert verdict_context["sender"].calls == []


def test_verdict_for_a_missing_user_does_not_send(
    verdict_context: dict[str, Any],
) -> None:
    """A deleted account produces no email rather than a crash loop."""
    result = kyc_notifications.send_kyc_verdict_notification.apply(
        kwargs={"user_id": str(uuid4()), "verified": True}
    ).get()

    assert result["status"] == "unknown_user"
    assert verdict_context["sender"].calls == []
