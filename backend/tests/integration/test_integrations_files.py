"""Integration tests for the Drive file browse endpoint.

Covers page mapping with importability flags, search forwarding, the
on-demand token refresh (including persistence and dead-grant handling),
and provider failure translation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
import pytest
import respx
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, select

from app.core.config import Settings, get_settings
from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    decrypt_connector_token,
    encrypt_connector_token,
    hash_password,
)
from app.main import app
from app.modules.auth.models import User
from app.modules.integrations.models import OAuthConnection
from tests.integration.test_auth_sessions import FakeRedis
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio

TOKEN_URL = "https://oauth2.googleapis.com/token"
FILES_URL = "https://www.googleapis.com/drive/v3/files"

DRIVE_SETTINGS = Settings(
    GOOGLE_CLIENT_ID="client-abc.apps.googleusercontent.com",
    GOOGLE_CLIENT_SECRET="gclient_secret",
    GOOGLE_DRIVE_REDIRECT_URI=(
        "https://auracles.space/v1/integrations/connectors/google-drive/callback"
    ),
)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure all tables exist before tests run."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def browse_context() -> AsyncIterator[dict[str, Any]]:
    """Configure Google settings + fake Redis and seed a contributor."""
    fake_redis = FakeRedis()
    await engine.dispose()
    async with async_session_factory() as session:
        await clear_identity_state_async(session)
        await session.commit()
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email="browse@auracles.space",
                password_hash=hash_password("password"),
                display_name="Browse Tester",
                email_verified=True,
                kyc_status="verified",
            )
            session.add(user)
            await session.flush()
            user_id = user.id
    app.dependency_overrides[get_settings] = lambda: DRIVE_SETTINGS
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield {"user_id": user_id}
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_redis, None)
        async with async_session_factory() as session:
            await clear_identity_state_async(session)
            await session.commit()
        await engine.dispose()


def _headers(user_id: UUID) -> dict[str, str]:
    token = create_access_token(user_id=user_id, roles=["contributor"])
    return {"Authorization": f"Bearer {token}"}


async def _seed_connection(
    user_id: UUID,
    *,
    access_token: str = "browse-at",
    refresh_token: str | None = "browse-rt",
    expires_in_seconds: int = 3600,
    status: str = "active",
) -> UUID:
    """Insert a Drive connection row and return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            connection = OAuthConnection(
                user_id=user_id,
                provider="google_drive",
                access_token_encrypted=encrypt_connector_token(access_token),
                refresh_token_encrypted=(
                    encrypt_connector_token(refresh_token)
                    if refresh_token is not None
                    else None
                ),
                token_expires_at=datetime.now(UTC)
                + timedelta(seconds=expires_in_seconds),
                scopes="https://www.googleapis.com/auth/drive.readonly",
                status=status,
            )
            session.add(connection)
            await session.flush()
            return connection.id


async def _connection(connection_id: UUID) -> OAuthConnection | None:
    async with async_session_factory() as session:
        return await session.scalar(
            select(OAuthConnection).where(OAuthConnection.id == connection_id)
        )


@respx.mock
async def test_browse_maps_files_with_importability(
    client: AsyncClient, migrated_database: None, browse_context: dict[str, Any]
) -> None:
    """Files map to schema fields; Office and Google-native are importable."""
    user_id = browse_context["user_id"]
    await _seed_connection(user_id)
    respx.get(FILES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "files": [
                    {
                        "id": "f1",
                        "name": "Plan.docx",
                        "mimeType": DOCX_MIME,
                        "size": "2048",
                    },
                    {
                        "id": "f2",
                        "name": "Native Doc",
                        "mimeType": "application/vnd.google-apps.document",
                    },
                    {
                        "id": "f3",
                        "name": "clip.mp4",
                        "mimeType": "video/mp4",
                        "size": "10",
                    },
                ],
                "nextPageToken": "cursor-2",
            },
        )
    )
    response = await client.get(
        "/v1/integrations/connectors/google-drive/files",
        headers=_headers(user_id),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["next_page_token"] == "cursor-2"
    by_id = {item["id"]: item for item in payload["files"]}
    assert by_id["f1"]["importable"] is True
    assert by_id["f1"]["size"] == 2048
    assert by_id["f2"]["importable"] is True
    assert by_id["f2"]["size"] is None
    assert by_id["f3"]["importable"] is False


@respx.mock
async def test_browse_forwards_escaped_query(
    client: AsyncClient, migrated_database: None, browse_context: dict[str, Any]
) -> None:
    """The search term reaches Drive escaped inside the q parameter."""
    user_id = browse_context["user_id"]
    await _seed_connection(user_id)
    route = respx.get(FILES_URL).mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    response = await client.get(
        "/v1/integrations/connectors/google-drive/files",
        params={"query": "bob's plan"},
        headers=_headers(user_id),
    )
    assert response.status_code == 200
    q = parse_qs(urlsplit(str(route.calls.last.request.url)).query)["q"][0]
    assert "name contains 'bob\\'s plan'" in q


@respx.mock
async def test_browse_refreshes_expiring_token_and_persists(
    client: AsyncClient, migrated_database: None, browse_context: dict[str, Any]
) -> None:
    """A near-expiry token is refreshed and the new token stored encrypted."""
    user_id = browse_context["user_id"]
    connection_id = await _seed_connection(
        user_id, access_token="stale-at", expires_in_seconds=10
    )
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "fresh-at", "expires_in": 3600}
        )
    )
    files_route = respx.get(FILES_URL).mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    response = await client.get(
        "/v1/integrations/connectors/google-drive/files",
        headers=_headers(user_id),
    )
    assert response.status_code == 200
    auth_header = files_route.calls.last.request.headers["Authorization"]
    assert auth_header == "Bearer fresh-at"

    row = await _connection(connection_id)
    assert row is not None
    assert row.access_token_encrypted is not None
    assert decrypt_connector_token(row.access_token_encrypted) == "fresh-at"


@respx.mock
async def test_browse_dead_refresh_grant_marks_reauth_required(
    client: AsyncClient, migrated_database: None, browse_context: dict[str, Any]
) -> None:
    """An invalid_grant refresh flips the connection to reauth_required."""
    user_id = browse_context["user_id"]
    connection_id = await _seed_connection(user_id, expires_in_seconds=10)
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    response = await client.get(
        "/v1/integrations/connectors/google-drive/files",
        headers=_headers(user_id),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "reauth_required"

    row = await _connection(connection_id)
    assert row is not None
    assert row.status == "reauth_required"


async def test_browse_without_connection_is_404(
    client: AsyncClient, migrated_database: None, browse_context: dict[str, Any]
) -> None:
    """Browsing with no stored connection returns 404."""
    response = await client.get(
        "/v1/integrations/connectors/google-drive/files",
        headers=_headers(browse_context["user_id"]),
    )
    assert response.status_code == 404


@respx.mock
async def test_browse_provider_failure_is_502(
    client: AsyncClient, migrated_database: None, browse_context: dict[str, Any]
) -> None:
    """A Drive 5xx surfaces as 502 without leaking provider internals."""
    user_id = browse_context["user_id"]
    await _seed_connection(user_id)
    respx.get(FILES_URL).mock(return_value=httpx.Response(500, text="boom"))
    response = await client.get(
        "/v1/integrations/connectors/google-drive/files",
        headers=_headers(user_id),
    )
    assert response.status_code == 502
    assert "boom" not in response.text
