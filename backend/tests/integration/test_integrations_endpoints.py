"""Integration tests for the connectors API (connect/callback/revoke/list).

Covers the Google Drive connection lifecycle: consent start with the
signed state cookie, the public callback with state validation, token
encryption at rest, reconnect upsert, revocation, and the GDPR export
entry.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, select

from app.core.config import Settings, get_settings
from app.core.cookies import (
    CONNECTOR_STATE_COOKIE_NAME,
    create_connector_state_value,
)
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
from app.modules.integrations.service import export_user_connections
from tests.integration.test_auth_sessions import FakeRedis
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio

TOKEN_URL = "https://oauth2.googleapis.com/token"
ABOUT_URL = "https://www.googleapis.com/drive/v3/about"

DRIVE_SETTINGS = Settings(
    GOOGLE_CLIENT_ID="client-abc.apps.googleusercontent.com",
    GOOGLE_CLIENT_SECRET="gclient_secret",
    GOOGLE_DRIVE_REDIRECT_URI=(
        "https://auracles.space/v1/integrations/connectors/google-drive/callback"
    ),
)


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
async def connector_context() -> AsyncIterator[dict[str, Any]]:
    """Configure Google settings + fake Redis and seed a contributor."""
    fake_redis = FakeRedis()
    await engine.dispose()
    async with async_session_factory() as session:
        await clear_identity_state_async(session)
        await session.commit()
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email="connector@auracles.space",
                password_hash=hash_password("password"),
                display_name="Connector Tester",
                email_verified=True,
                kyc_status="verified",
            )
            session.add(user)
            await session.flush()
            user_id = user.id
    app.dependency_overrides[get_settings] = lambda: DRIVE_SETTINGS
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield {"user_id": user_id, "redis": fake_redis}
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_redis, None)
        async with async_session_factory() as session:
            await clear_identity_state_async(session)
            await session.commit()
        await engine.dispose()


def _headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Bearer auth headers with the given role claims."""
    return {
        "Authorization": f"Bearer {create_access_token(user_id=user_id, roles=roles)}"
    }


async def _connection_rows(user_id: UUID) -> list[OAuthConnection]:
    async with async_session_factory() as session:
        return list(
            (
                await session.execute(
                    select(OAuthConnection).where(
                        OAuthConnection.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )


def _state_cookie(client: AsyncClient, user_id: UUID, state: str = "state-1") -> None:
    """Plant a valid signed connector state cookie on the test client."""
    client.cookies.set(
        CONNECTOR_STATE_COOKIE_NAME,
        create_connector_state_value(
            state=state,
            verifier="verifier-1",
            user_id=str(user_id),
            settings=DRIVE_SETTINGS,
        ),
    )


def _mock_google_exchange() -> None:
    """Mock the token exchange and account-email lookup."""
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "drive-at",
                "refresh_token": "drive-rt",
                "expires_in": 3600,
            },
        )
    )
    respx.get(ABOUT_URL).mock(
        return_value=httpx.Response(
            200, json={"user": {"emailAddress": "pro@gmail.com"}}
        )
    )


async def test_list_connectors_requires_auth(
    client: AsyncClient, migrated_database: None, connector_context: dict[str, Any]
) -> None:
    """Listing connectors unauthenticated returns 401."""
    response = await client.get("/v1/integrations/connectors")
    assert response.status_code == 401


async def test_list_connectors_reports_disconnected_provider(
    client: AsyncClient, migrated_database: None, connector_context: dict[str, Any]
) -> None:
    """Every supported provider appears, disconnected by default."""
    response = await client.get(
        "/v1/integrations/connectors",
        headers=_headers(connector_context["user_id"], ["contributor"]),
    )
    assert response.status_code == 200
    connectors = response.json()["connectors"]
    assert connectors == [{
        "provider": "google-drive",
        "connected": False,
        "connection_id": None,
        "status": None,
        "account_email": None,
    }]


async def test_connect_rejects_non_contributor(
    client: AsyncClient, migrated_database: None, connector_context: dict[str, Any]
) -> None:
    """Only contributors may start a connector consent flow."""
    response = await client.post(
        "/v1/integrations/connectors/google-drive/connect",
        headers=_headers(connector_context["user_id"], ["operator"]),
    )
    assert response.status_code == 403


async def test_connect_returns_consent_url_and_state_cookie(
    client: AsyncClient, migrated_database: None, connector_context: dict[str, Any]
) -> None:
    """Connect returns the Drive consent URL and seals the state cookie."""
    response = await client.post(
        "/v1/integrations/connectors/google-drive/connect",
        headers=_headers(connector_context["user_id"], ["contributor"]),
    )
    assert response.status_code == 200
    url = response.json()["authorization_url"]
    assert "accounts.google.com" in url
    assert "drive.readonly" in url
    set_cookie = response.headers.get("set-cookie", "")
    assert CONNECTOR_STATE_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie
    # The browser reaches the callback through the frontend `/api` proxy, so the
    # path it sees is `/api/v1/integrations/...`. A cookie scoped to
    # `/v1/integrations` never rides along there (path prefix mismatch), so the
    # callback fails with "Invalid connector state". The cookie must be root-path
    # so it survives the proxy — matching every other auth cookie.
    cookie_path = next(
        (
            attr.strip().split("=", 1)[1]
            for attr in set_cookie.split(";")
            if attr.strip().lower().startswith("path=")
        ),
        None,
    )
    assert cookie_path == "/"


async def test_connect_unknown_provider_is_404(
    client: AsyncClient, migrated_database: None, connector_context: dict[str, Any]
) -> None:
    """Unknown providers 404 rather than reaching any OAuth logic."""
    response = await client.post(
        "/v1/integrations/connectors/dropbox/connect",
        headers=_headers(connector_context["user_id"], ["contributor"]),
    )
    assert response.status_code == 404


async def test_callback_rejects_state_mismatch(
    client: AsyncClient, migrated_database: None, connector_context: dict[str, Any]
) -> None:
    """A state that does not match the signed cookie is rejected."""
    user_id = connector_context["user_id"]
    _state_cookie(client, user_id, state="expected-state")
    try:
        response = await client.get(
            "/v1/integrations/connectors/google-drive/callback",
            params={"code": "code-1", "state": "attacker-state"},
        )
    finally:
        client.cookies.delete(CONNECTOR_STATE_COOKIE_NAME)
    assert response.status_code == 400
    assert await _connection_rows(user_id) == []


@respx.mock
async def test_callback_happy_path_stores_encrypted_tokens(
    client: AsyncClient, migrated_database: None, connector_context: dict[str, Any]
) -> None:
    """The callback exchanges the code, encrypts tokens, and redirects."""
    user_id = connector_context["user_id"]
    _mock_google_exchange()
    _state_cookie(client, user_id)
    try:
        response = await client.get(
            "/v1/integrations/connectors/google-drive/callback",
            params={"code": "code-1", "state": "state-1"},
        )
    finally:
        client.cookies.delete(CONNECTOR_STATE_COOKIE_NAME)
    assert response.status_code == 302
    assert response.headers["location"] == (
        "https://auracles.space/settings/integrations"
        "?connector=google-drive&status=connected"
    )

    rows = await _connection_rows(user_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "active"
    assert row.provider == "google_drive"
    assert row.provider_account_email == "pro@gmail.com"
    assert row.access_token_encrypted is not None
    assert row.access_token_encrypted != "drive-at"
    assert decrypt_connector_token(row.access_token_encrypted) == "drive-at"
    assert row.refresh_token_encrypted is not None
    assert decrypt_connector_token(row.refresh_token_encrypted) == "drive-rt"

    listed = await client.get(
        "/v1/integrations/connectors",
        headers=_headers(user_id, ["contributor"]),
    )
    entry = listed.json()["connectors"][0]
    assert entry["connected"] is True
    assert entry["account_email"] == "pro@gmail.com"


@respx.mock
async def test_reconnect_replaces_tokens_on_single_row(
    client: AsyncClient, migrated_database: None, connector_context: dict[str, Any]
) -> None:
    """Reconnecting upserts the existing row instead of adding another."""
    user_id = connector_context["user_id"]
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OAuthConnection(
                    user_id=user_id,
                    provider="google_drive",
                    access_token_encrypted=encrypt_connector_token("old-at"),
                    scopes="old-scope",
                    status="reauth_required",
                )
            )
    _mock_google_exchange()
    _state_cookie(client, user_id)
    try:
        response = await client.get(
            "/v1/integrations/connectors/google-drive/callback",
            params={"code": "code-2", "state": "state-1"},
        )
    finally:
        client.cookies.delete(CONNECTOR_STATE_COOKIE_NAME)
    assert response.status_code == 302

    rows = await _connection_rows(user_id)
    assert len(rows) == 1
    assert rows[0].status == "active"
    assert rows[0].access_token_encrypted is not None
    assert decrypt_connector_token(rows[0].access_token_encrypted) == "drive-at"


async def test_revoke_clears_tokens_and_is_idempotent(
    client: AsyncClient, migrated_database: None, connector_context: dict[str, Any]
) -> None:
    """Disconnect marks the row revoked, drops tokens, and re-runs cleanly."""
    user_id = connector_context["user_id"]
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OAuthConnection(
                    user_id=user_id,
                    provider="google_drive",
                    access_token_encrypted=encrypt_connector_token("live-at"),
                    refresh_token_encrypted=encrypt_connector_token("live-rt"),
                    scopes="scope",
                )
            )
    headers = _headers(user_id, ["contributor"])
    with respx.mock:
        respx.post("https://oauth2.googleapis.com/revoke").mock(
            return_value=httpx.Response(200)
        )
        first = await client.delete(
            "/v1/integrations/connectors/google-drive", headers=headers
        )
        second = await client.delete(
            "/v1/integrations/connectors/google-drive", headers=headers
        )
    assert first.status_code == 204
    assert second.status_code == 204

    rows = await _connection_rows(user_id)
    assert len(rows) == 1
    assert rows[0].status == "revoked"
    assert rows[0].access_token_encrypted is None
    assert rows[0].refresh_token_encrypted is None

    listed = await client.get("/v1/integrations/connectors", headers=headers)
    assert listed.json()["connectors"][0]["connected"] is False


async def test_gdpr_export_lists_connection_metadata_only(
    client: AsyncClient, migrated_database: None, connector_context: dict[str, Any]
) -> None:
    """The GDPR export carries provider metadata and never token material."""
    user_id = connector_context["user_id"]
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OAuthConnection(
                    user_id=user_id,
                    provider="google_drive",
                    access_token_encrypted=encrypt_connector_token("secret-at"),
                    provider_account_email="pro@gmail.com",
                    scopes="scope",
                )
            )
    async with async_session_factory() as session:
        exported = await export_user_connections(session, user_id=user_id)
    assert exported == [
        {
            "provider": "google_drive",
            "account_email": "pro@gmail.com",
            "status": "active",
            "connected_at": exported[0]["connected_at"],
        }
    ]
    assert "secret-at" not in str(exported)
