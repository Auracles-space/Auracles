"""Unit tests for GDPR anonymisation of connector grants."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.core.security import encrypt_connector_token
from app.modules.auth.models import User
from app.modules.gdpr.models import AccountDeletionRequest
from app.modules.integrations.models import OAuthConnection
from tests.support.db_cleanup import clear_identity_state_async


async def _cleanup_gdpr_rows() -> None:
    """Remove GDPR deletion rows before identity cleanup."""
    async with async_session_factory() as session:
        await session.execute(delete(AccountDeletionRequest))
        await clear_identity_state_async(session)
        await session.commit()


@pytest.fixture
async def gdpr_user_with_connection(
    migrated_database: None,
) -> AsyncIterator[tuple[AsyncSession, User, UUID, OAuthConnection]]:
    """Seed one scheduled deletion request and one stored Drive connection."""
    await engine.dispose()
    await _cleanup_gdpr_rows()

    session = async_session_factory()
    user = User(
        email="gdpr-connector@auracles.space",
        display_name="GDPR Connector",
        email_verified=True,
        password_hash=None,
    )
    deletion_request = AccountDeletionRequest(
        user_id=UUID(int=0),
        status="scheduled",
        scheduled_for=datetime.now(UTC) + timedelta(days=7),
    )
    connection = OAuthConnection(
        user_id=UUID(int=0),
        provider="google_drive",
        access_token_encrypted=encrypt_connector_token("access-token"),
        refresh_token_encrypted=encrypt_connector_token("refresh-token"),
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes="https://www.googleapis.com/auth/drive.readonly",
        status="active",
    )

    async with session.begin():
        session.add(user)
        await session.flush()
        deletion_request.user_id = user.id
        connection.user_id = user.id
        session.add(deletion_request)
        session.add(connection)
        await session.flush()

    yield session, user, deletion_request.id, connection

    await session.close()
    await _cleanup_gdpr_rows()
    await engine.dispose()


@pytest.mark.asyncio
async def test_anonymise_revokes_and_deletes_oauth_connections(
    monkeypatch: pytest.MonkeyPatch,
    gdpr_user_with_connection: tuple[AsyncSession, User, UUID, OAuthConnection],
) -> None:
    """Account deletion revokes stored tokens and deletes connection rows."""
    from app.modules.gdpr import anonymise

    db, user, request_id, _connection = gdpr_user_with_connection
    revoked: list[str] = []

    async def _revoke(token: str) -> None:
        """Record each revoke attempt instead of calling Google."""
        revoked.append(token)

    monkeypatch.setattr(anonymise, "revoke_drive_token", _revoke, raising=False)

    await anonymise.anonymise_user_records(
        db=db,
        user_id=user.id,
        request_id=request_id,
        completed_at=datetime.now(UTC),
    )

    remaining = (
        await db.execute(
            select(OAuthConnection).where(OAuthConnection.user_id == user.id)
        )
    ).scalars().all()
    assert remaining == []
    assert revoked == ["access-token", "refresh-token"]


@pytest.mark.asyncio
async def test_anonymise_deletes_connections_even_if_revoke_fails(
    monkeypatch: pytest.MonkeyPatch,
    gdpr_user_with_connection: tuple[AsyncSession, User, UUID, OAuthConnection],
) -> None:
    """Connection rows are purged even if Google revoke raises unexpectedly."""
    from app.modules.gdpr import anonymise

    db, user, request_id, _connection = gdpr_user_with_connection
    attempts: list[str] = []

    async def _revoke(token: str) -> None:
        """Raise after recording the revoke attempt."""
        attempts.append(token)
        raise RuntimeError("google revoke failed")

    monkeypatch.setattr(anonymise, "revoke_drive_token", _revoke, raising=False)

    await anonymise.anonymise_user_records(
        db=db,
        user_id=user.id,
        request_id=request_id,
        completed_at=datetime.now(UTC),
    )

    remaining = (
        await db.execute(
            select(OAuthConnection).where(OAuthConnection.user_id == user.id)
        )
    ).scalars().all()
    assert remaining == []
    assert attempts == ["access-token", "refresh-token"]
