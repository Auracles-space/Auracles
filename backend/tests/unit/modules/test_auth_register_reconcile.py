"""Unit tests for register-time org invitation reconciliation.

Registering with an email that already has a pending organization invitation
must create the in-app notification the invitee would have missed before the
account existed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password, hash_token
from app.main import app
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.auth.schemas import RegisterRequest
from app.modules.notifications.models import Notification
from app.modules.organizations.models import Organization, OrgInvitation, OrgMember
from tests.integration.test_auth_registration import FakeRedis, SentVerificationEmails
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for register reconciliation tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        command.upgrade(alembic_config, "head")
        sync_engine.dispose()


@pytest.fixture
async def auth_register_state(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FakeRedis]:
    """Reset auth/org rows and replace verification dispatch with a recorder."""
    fake_redis = FakeRedis()
    sent_emails = SentVerificationEmails()
    monkeypatch.setattr(auth_service, "send_verification_email", sent_emails)
    await engine.dispose()

    async def cleanup() -> None:
        """Delete invitation rows before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(OrgInvitation))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    try:
        yield fake_redis
    finally:
        await cleanup()
        await engine.dispose()


@pytest.fixture
async def make_pending_invite() -> AsyncIterator[object]:
    """Return a helper that inserts one pending invitation for an email."""

    async def _make_pending_invite(*, email: str) -> None:
        """Insert an active org, owner membership, and pending invitation."""
        async with async_session_factory() as session:
            async with session.begin():
                owner = User(
                    email=f"owner-{uuid4().hex[:8]}@auracles.space",
                    password_hash=hash_password("CorrectHorse9"),
                    display_name="owner",
                    email_verified=True,
                )
                session.add(owner)
                await session.flush()
                organization = Organization(
                    slug=f"reconcile-org-{uuid4().hex[:6]}",
                    name="Reconcile Org",
                    country="GB",
                    created_by=owner.id,
                )
                session.add(organization)
                await session.flush()
                session.add(
                    OrgMember(org_id=organization.id, user_id=owner.id, role="owner")
                )
                session.add(
                    OrgInvitation(
                        org_id=organization.id,
                        email=email,
                        role="member",
                        invited_by=owner.id,
                        status="pending",
                        token_hash=hash_token(uuid4().hex),
                        expires_at=datetime.now(UTC) + timedelta(days=7),
                    )
                )

    yield _make_pending_invite


@pytest.mark.asyncio
async def test_register_creates_notification_for_pending_invite(
    migrated_database: None,
    auth_register_state: FakeRedis,
    make_pending_invite: object,
) -> None:
    """Registering with an email that has a pending invite writes a notification."""
    del migrated_database
    email = "newbie@example.com"
    await make_pending_invite(email=email)  # type: ignore[misc]

    async with async_session_factory() as session:
        await auth_service.register_user(
            session,
            auth_register_state,
            RegisterRequest(
                email=email,
                password="StrongerPass123!",  # type: ignore[arg-type]
                display_name="Newbie",
                roles=["operator"],
            ),
        )

    async with async_session_factory() as session:
        notes = (
            await session.execute(
                select(Notification).where(
                    Notification.notification_type == "org_invitation_received"
                )
            )
        ).scalars().all()

    assert len(notes) == 1


@pytest.mark.asyncio
async def test_register_without_invite_creates_no_notification(
    migrated_database: None,
    auth_register_state: FakeRedis,
) -> None:
    """No pending invite means registration creates no invitation notification."""
    del migrated_database

    async with async_session_factory() as session:
        await auth_service.register_user(
            session,
            auth_register_state,
            RegisterRequest(
                email="solo@example.com",
                password="StrongerPass123!",  # type: ignore[arg-type]
                display_name="Solo",
                roles=["operator"],
            ),
        )

    async with async_session_factory() as session:
        notes = (
            await session.execute(
                select(Notification).where(
                    Notification.notification_type == "org_invitation_received"
                )
            )
        ).scalars().all()

    assert notes == []
