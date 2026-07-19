"""Wiring tests: user submissions fan out an admin-review notification.

These prove the service call sites invoke `notify_admins_review_pending` with
the correct domain and target after the domain state commits. The fan-out task
itself is covered in tests/unit/workers/test_admin_notification_tasks.py; here
we patch the helper so the assertion is deterministic and broker-free.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.auth.models import User, UserRole
from app.modules.developer import application_service
from app.modules.developer.schemas import DeveloperApplicationCreateRequest
from tests.support.db_cleanup import clear_identity_state_sync

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure all tables exist for service-level wiring tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
def cleanup_identity() -> Iterator[None]:
    """Clear users/roles before and after each wiring test."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)

    def _clear() -> None:
        with session_factory() as session:
            clear_identity_state_sync(session)
            session.commit()

    _clear()
    try:
        yield
    finally:
        _clear()
        sync_engine.dispose()


def _create_user(email: str) -> UUID:
    """Create one verified operator user and return its id."""
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
            UserRole(user_id=user.id, role="operator", approved_at=datetime.now(UTC))
        )
        session.commit()
        user_id = user.id
    sync_engine.dispose()
    return user_id


async def test_submit_application_notifies_admins(
    migrated_database: None,
    cleanup_identity: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Submitting a Developer application fans out to admins for the new record."""
    calls: list[dict[str, Any]] = []

    def _capture(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(application_service, "notify_admins_review_pending", _capture)

    # Integration tests dispose the shared async engine in teardown; re-initialize
    # its pool on the current event loop before using async_session_factory.
    await engine.dispose()

    user_id = _create_user("dev-applicant@auracles.space")
    async with async_session_factory() as db:
        user = await db.get(User, user_id)
        assert user is not None
        application = await application_service.submit_application(
            db=db,
            user=user,
            payload=DeveloperApplicationCreateRequest(
                company_name="Acme Analytics",
                use_case="We integrate framework purchases into our analytics suite.",
            ),
        )

    assert len(calls) == 1
    assert calls[0]["domain"] == "developer_application"
    assert calls[0]["target_id"] == application.id
    assert calls[0]["link"] == "/admin/developer"
