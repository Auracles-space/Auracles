"""Notification Celery task tests.

Covers the dispatch wrappers in ``app/workers/tasks/notifications.py``. Each
wrapper logs, calls a Resend integration function, and retries on failure. The
Resend functions are patched to record calls (happy path) or raise (retry
path), so no real email is sent. ``notify_licensees_of_new_version`` runs an
async DB query via the worker loop and is driven through ``asyncio.to_thread``
with the shared engine disposed around the hop.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from celery.exceptions import Retry
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.main import app
from app.modules.frameworks.models import License
from app.workers.tasks import notifications


class _Recorder:
    """Capture the keyword arguments of the most recent call."""

    def __init__(self) -> None:
        """Start with no recorded call."""
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> None:
        """Record one call's keyword arguments."""
        self.calls.append(kwargs)


def test_send_verification_email_dispatches_to_resend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verification task forwards email and token to Resend."""
    recorder = _Recorder()
    monkeypatch.setattr(notifications, "send_via_resend", recorder)

    notifications.send_verification_email.apply(
        args=["user@auracles.space", "tok-1"]
    ).get()

    assert recorder.calls == [{"email": "user@auracles.space", "token": "tok-1"}]


def test_send_password_reset_email_dispatches_to_resend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The password-reset task forwards email and token to Resend."""
    recorder = _Recorder()
    monkeypatch.setattr(notifications, "send_password_reset_via_resend", recorder)

    notifications.send_password_reset_email.apply(
        args=["user@auracles.space", "reset-1"]
    ).get()

    assert recorder.calls == [{"email": "user@auracles.space", "token": "reset-1"}]


def test_send_email_change_verification_dispatches_to_resend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The email-change task forwards the new email and token to Resend."""
    recorder = _Recorder()
    monkeypatch.setattr(notifications, "send_email_change_via_resend", recorder)

    notifications.send_email_change_verification.apply(
        args=["new@auracles.space", "change-1"]
    ).get()

    assert recorder.calls == [{"email": "new@auracles.space", "token": "change-1"}]


def test_send_new_device_email_dispatches_to_resend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new-device task forwards email, ip, and user agent to Resend."""
    recorder = _Recorder()
    monkeypatch.setattr(notifications, "send_new_device_via_resend", recorder)

    notifications.send_new_device_email.apply(
        args=["user@auracles.space", "203.0.113.4", "Firefox"]
    ).get()

    assert recorder.calls == [
        {"email": "user@auracles.space", "ip": "203.0.113.4", "user_agent": "Firefox"}
    ]


def test_send_project_notification_email_dispatches_to_resend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The project-notification task forwards the templated fields to Resend."""
    recorder = _Recorder()
    monkeypatch.setattr(notifications, "send_project_notification_via_resend", recorder)

    notifications.send_project_notification_email.apply(
        kwargs={
            "email": "op@auracles.space",
            "title": "Milestone funded",
            "body": "Your milestone was funded.",
            "link": "https://auracles.space/projects/1",
        }
    ).get()

    assert recorder.calls == [
        {
            "email": "op@auracles.space",
            "title": "Milestone funded",
            "body": "Your milestone was funded.",
            "link": "https://auracles.space/projects/1",
        }
    ]


def test_send_saved_search_alert_email_renders_match_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The saved-search digest renders each match into the notification body."""
    recorder = _Recorder()
    monkeypatch.setattr(notifications, "send_project_notification_via_resend", recorder)

    notifications.send_saved_search_alert_email.apply(
        kwargs={
            "email": "op@auracles.space",
            "saved_search_name": "Risk frameworks",
            "matches": [
                {"title": "Board Risk OS", "link": "https://auracles.space/f/1"},
            ],
            "link": "https://auracles.space/searches/1",
        }
    ).get()

    assert len(recorder.calls) == 1
    sent = recorder.calls[0]
    assert sent["title"] == "New Auracles matches for Risk frameworks"
    assert "Board Risk OS: https://auracles.space/f/1" in sent["body"]


def test_send_verification_email_retries_when_resend_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Resend failure raises Celery Retry instead of crashing the worker."""

    def _boom(**_kwargs: Any) -> None:
        raise RuntimeError("resend down")

    monkeypatch.setattr(notifications, "send_via_resend", _boom)

    with pytest.raises(Retry):
        notifications.send_verification_email.apply(
            args=["user@auracles.space", "tok-1"], throw=True
        )


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure framework/license tables exist for the licensee-count task."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def empty_license_state() -> AsyncIterator[None]:
    """Clear licenses so the new-version notification counts a clean zero."""
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(License))
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def test_notify_licensees_of_new_version_counts_active_licenses(
    migrated_database: None,
    empty_license_state: None,
) -> None:
    """The task reports the active-license count for a new published version."""
    del migrated_database, empty_license_state
    framework_id = "00000000-0000-0000-0000-0000000000aa"

    await engine.dispose()
    result: dict[str, Any] = await asyncio.to_thread(
        lambda: notifications.notify_licensees_of_new_version.apply(
            args=[framework_id, "2.0.0"]
        ).get()
    )
    await engine.dispose()

    assert result == {
        "framework_id": framework_id,
        "new_version": "2.0.0",
        "active_license_count": 0,
    }


@pytest.mark.parametrize(
    ("task", "resend_attr", "apply_kwargs"),
    [
        (
            notifications.send_password_reset_email,
            "send_password_reset_via_resend",
            {"args": ["user@auracles.space", "reset-1"]},
        ),
        (
            notifications.send_email_change_verification,
            "send_email_change_via_resend",
            {"args": ["new@auracles.space", "change-1"]},
        ),
        (
            notifications.send_new_device_email,
            "send_new_device_via_resend",
            {"args": ["user@auracles.space", "203.0.113.4", "Firefox"]},
        ),
        (
            notifications.send_project_notification_email,
            "send_project_notification_via_resend",
            {"kwargs": {"email": "op@auracles.space", "title": "t", "body": "b"}},
        ),
        (
            notifications.send_saved_search_alert_email,
            "send_project_notification_via_resend",
            {
                "kwargs": {
                    "email": "op@auracles.space",
                    "saved_search_name": "Risk",
                    "matches": [{"title": "F", "link": "https://a.test/f"}],
                }
            },
        ),
    ],
)
def test_notification_wrappers_retry_when_resend_fails(
    monkeypatch: pytest.MonkeyPatch,
    task: Any,
    resend_attr: str,
    apply_kwargs: dict[str, Any],
) -> None:
    """Every Resend-backed wrapper raises Celery Retry on a provider failure."""

    def _boom(**_kwargs: Any) -> None:
        raise RuntimeError("resend down")

    monkeypatch.setattr(notifications, resend_attr, _boom)

    with pytest.raises(Retry):
        task.apply(throw=True, **apply_kwargs)


def test_notify_licensees_retries_on_db_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure inside the licensee-count query raises Celery Retry."""

    async def _boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("db down")

    monkeypatch.setattr(notifications, "_notify_licensees_of_new_version_impl", _boom)

    with pytest.raises(Retry):
        notifications.notify_licensees_of_new_version.apply(
            args=["00000000-0000-0000-0000-0000000000aa", "2.0.0"], throw=True
        )
