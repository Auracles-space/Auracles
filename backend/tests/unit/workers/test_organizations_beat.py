"""Unit tests for the organization invitation expiry beat task.

Validates that expire_pending_org_invitations correctly flips pending
invitations past their expiry window, leaves non-pending invitations
untouched, and no-ops on an empty table. Uses the same cross-loop
pattern as other beat task tests: dispose engine → run task via
asyncio.to_thread → dispose engine.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from celery.schedules import crontab
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import hash_password, hash_token
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.organizations.models import (
    Organization,
    OrgInvitation,
    OrgMember,
)
from app.shared.models.audit_log import AuditLog
from app.workers.beat_schedule import BEAT_SCHEDULE
from app.workers.tasks.organizations_beat import expire_pending_org_invitations


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure org tables exist before the beat task runs."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_org_state() -> AsyncIterator[None]:
    """Reset invitation + org rows so each test starts clean."""
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(OrgInvitation))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _run_beat(task: object) -> dict[str, int]:
    """Run a Celery beat task in a worker thread and return its result dict."""
    await engine.dispose()
    result: dict[str, int] = await asyncio.to_thread(lambda: task.apply().get())
    await engine.dispose()
    return result


async def _seed_invitation(*, expires_at: datetime, status: str = "pending") -> UUID:
    """Insert an invitation with a specific expiry and status."""
    async with async_session_factory() as session:
        async with session.begin():
            owner = User(
                email=f"beat-owner-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="beat-owner",
                email_verified=True,
            )
            session.add(owner)
            await session.flush()
            org = Organization(
                slug=f"beat-org-{uuid4().hex[:6]}",
                name="Beat Org",
                country="GB",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            invitation = OrgInvitation(
                org_id=org.id,
                email=f"beat-invitee-{uuid4().hex[:8]}@auracles.space",
                role="member",
                invited_by=owner.id,
                status=status,
                token_hash=hash_token(uuid4().hex),
                expires_at=expires_at,
            )
            session.add(invitation)
            await session.flush()
            return invitation.id


async def test_beat_schedule_registered() -> None:
    """The org invitation expiry task runs daily at a pinned UTC time.

    A crontab schedule (not a float interval) keeps the sweep at a
    predictable off-peak hour regardless of when Beat was restarted.
    """
    assert "expire-pending-org-invitations-daily" in BEAT_SCHEDULE
    entry = BEAT_SCHEDULE["expire-pending-org-invitations-daily"]
    assert entry["task"] == (
        "app.workers.tasks.organizations_beat.expire_pending_org_invitations"
    )
    assert entry["schedule"] == crontab(hour=3, minute=20)


async def test_noop_on_empty_table(
    migrated_database: None,
    clean_org_state: None,
) -> None:
    """With no pending invitations the task returns expired_count=0."""
    del migrated_database, clean_org_state
    result = await _run_beat(expire_pending_org_invitations)
    assert result == {"expired_count": 0}


async def test_expires_overdue_pending_invitation(
    migrated_database: None,
    clean_org_state: None,
) -> None:
    """A pending invitation past its expiry window gets status='expired'."""
    del migrated_database, clean_org_state
    inv_id = await _seed_invitation(
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    result = await _run_beat(expire_pending_org_invitations)

    assert result["expired_count"] == 1
    async with async_session_factory() as session:
        invitation = await session.get(OrgInvitation, inv_id)
    assert invitation is not None
    assert invitation.status == "expired"
    assert invitation.responded_at is not None


async def test_skips_non_pending_invitations(
    migrated_database: None,
    clean_org_state: None,
) -> None:
    """Already-accepted invitations past their expiry are not touched."""
    del migrated_database, clean_org_state
    inv_id = await _seed_invitation(
        expires_at=datetime.now(UTC) - timedelta(hours=1),
        status="accepted",
    )
    result = await _run_beat(expire_pending_org_invitations)

    assert result["expired_count"] == 0
    async with async_session_factory() as session:
        invitation = await session.get(OrgInvitation, inv_id)
    assert invitation is not None
    assert invitation.status == "accepted"


async def test_skips_future_pending_invitations(
    migrated_database: None,
    clean_org_state: None,
) -> None:
    """Pending invitations still within their window are not expired."""
    del migrated_database, clean_org_state
    inv_id = await _seed_invitation(
        expires_at=datetime.now(UTC) + timedelta(days=3),
    )
    result = await _run_beat(expire_pending_org_invitations)

    assert result["expired_count"] == 0
    async with async_session_factory() as session:
        invitation = await session.get(OrgInvitation, inv_id)
    assert invitation is not None
    assert invitation.status == "pending"
