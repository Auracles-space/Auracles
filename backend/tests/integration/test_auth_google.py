"""Integration tests for the Google sign-in start endpoint.

Slice 1 covers only ``GET /v1/auth/google/start``: build the consent redirect,
plant the signed HttpOnly state cookie (CSRF + PKCE verifier), and refuse when
Google is not configured. The callback lands in slice 2.

Maps to: Google Auth + Onboarding + 2FA design, build slice 1.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.config import Settings, get_settings
from app.core.cookies import (
    OAUTH_STATE_COOKIE_NAME,
    create_oauth_state_value,
    read_oauth_state_value,
)
from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import hash_password
from app.integrations.google_oauth import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GoogleClaims,
)
from app.main import app
from app.modules.auth import router as auth_router
from app.modules.auth.models import OAuthAccount, User, UserRole
from app.modules.gdpr.models import ConsentLog
from app.shared.models.audit_log import AuditLog
from tests.integration.test_auth_sessions import FakeRedis

GOOGLE_SETTINGS = Settings(
    GOOGLE_CLIENT_ID="client-abc.apps.googleusercontent.com",
    GOOGLE_CLIENT_SECRET="gclient_secret",
    GOOGLE_REDIRECT_URI="https://auracles.space/v1/auth/google/callback",
)


@pytest.fixture
def google_configured() -> Iterator[None]:
    """Override settings so the app has Google OAuth credentials."""
    app.dependency_overrides[get_settings] = lambda: GOOGLE_SETTINGS
    yield
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure auth tables exist for the callback tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url, pool_pre_ping=True
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def google_context() -> AsyncIterator[dict[str, Any]]:
    """Install fake Redis and reset auth tables for callback tests."""
    fake_redis = FakeRedis()
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(ConsentLog))
        await session.execute(delete(OAuthAccount))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield {"redis": fake_redis}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await engine.dispose()


def _stub_google(monkeypatch: pytest.MonkeyPatch, claims: GoogleClaims) -> None:
    """Bypass Google network calls so callback tests exercise our own logic."""

    async def _exchange(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"id_token": "stub-id-token"}

    async def _jwks(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"keys": []}

    def _verify(*args: Any, **kwargs: Any) -> GoogleClaims:
        return claims

    monkeypatch.setattr(auth_router, "exchange_code", _exchange)
    monkeypatch.setattr(auth_router, "fetch_google_jwks", _jwks)
    monkeypatch.setattr(auth_router, "verify_id_token", _verify)


async def _seed_state(redis: FakeRedis, terms_accepted: bool = True) -> str:
    """Return a signed state cookie value with a known state token."""
    return create_oauth_state_value(
        state="known-state",
        verifier="known-verifier",
        next_path=None,
        terms_accepted=terms_accepted,
        settings=GOOGLE_SETTINGS,
    )


async def _user_by_email(email: str) -> User | None:
    async with async_session_factory() as session:
        return await session.scalar(select(User).where(User.email == email))


async def _oauth_rows() -> list[OAuthAccount]:
    async with async_session_factory() as session:
        return list((await session.scalars(select(OAuthAccount))).all())


@pytest.mark.asyncio
async def test_start_redirects_to_google_with_state_cookie(
    client: AsyncClient,
    google_configured: None,
) -> None:
    """The start endpoint 302s to Google and plants a matching state cookie."""
    response = await client.get("/v1/auth/google/start")

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(GOOGLE_AUTHORIZATION_ENDPOINT)

    raw_cookie = response.cookies.get(OAUTH_STATE_COOKIE_NAME)
    assert raw_cookie is not None
    payload = read_oauth_state_value(raw_cookie, settings=GOOGLE_SETTINGS)
    assert payload is not None
    # The state in the redirect must equal the state stored in the cookie so the
    # callback can prove the response is the one we initiated (CSRF).
    assert f"state={payload['state']}" in location
    # The PKCE verifier is sealed in the HttpOnly cookie, never in the URL.
    assert isinstance(payload["verifier"], str) and payload["verifier"]
    assert str(payload["verifier"]) not in location


@pytest.mark.asyncio
async def test_start_preserves_next_path_in_state(
    client: AsyncClient,
    google_configured: None,
) -> None:
    """A ?next= intent is sealed into the state cookie for post-login resume."""
    response = await client.get("/v1/auth/google/start?next=/explore/abc")

    payload = read_oauth_state_value(
        response.cookies.get(OAUTH_STATE_COOKIE_NAME),
        settings=GOOGLE_SETTINGS,
    )
    assert payload is not None
    assert payload["next"] == "/explore/abc"


@pytest.mark.asyncio
async def test_start_returns_503_when_google_not_configured(
    client: AsyncClient,
) -> None:
    """Without Google credentials the endpoint refuses cleanly (not a 500)."""
    response = await client.get("/v1/auth/google/start")

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_callback_rejects_state_mismatch(
    client: AsyncClient,
    google_configured: None,
    migrated_database: None,
    google_context: dict[str, Any],
) -> None:
    """A returned state that does not match the cookie is rejected (CSRF guard)."""
    cookie = await _seed_state(google_context["redis"])
    client.cookies.set(OAUTH_STATE_COOKIE_NAME, cookie)

    response = await client.get(
        "/v1/auth/google/callback?code=abc&state=WRONG-state"
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_callback_rejects_missing_state_cookie(
    client: AsyncClient,
    google_configured: None,
    migrated_database: None,
    google_context: dict[str, Any],
) -> None:
    """Without the signed state cookie the callback cannot be trusted."""
    response = await client.get(
        "/v1/auth/google/callback?code=abc&state=known-state"
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_callback_creates_passwordless_user_and_redirects_to_onboarding(
    client: AsyncClient,
    google_configured: None,
    migrated_database: None,
    google_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A brand-new Google user is created roleless and sent to onboarding."""
    _stub_google(
        monkeypatch,
        GoogleClaims(
            sub="sub-new",
            email="newuser@example.com",
            email_verified=True,
            name="New User",
        ),
    )
    client.cookies.set(
        OAUTH_STATE_COOKIE_NAME, await _seed_state(google_context["redis"])
    )

    response = await client.get(
        "/v1/auth/google/callback?code=abc&state=known-state"
    )

    assert response.status_code == 302
    assert "/settings/onboarding" in response.headers["location"]
    # Session cookies are set so the frontend can mint an access token.
    assert response.cookies.get("refresh_token") is not None
    assert response.cookies.get("session_hint") is not None

    user = await _user_by_email("newuser@example.com")
    assert user is not None
    assert user.password_hash is None
    assert user.email_verified is True
    assert user.display_name == "New User"
    rows = await _oauth_rows()
    assert [(r.provider, r.provider_id) for r in rows] == [("google", "sub-new")]
    # The Terms acceptance carried from sign-up is recorded as consent.
    async with async_session_factory() as session:
        consent_rows = list(
            (
                await session.scalars(
                    select(ConsentLog).where(ConsentLog.user_id == user.id)
                )
            ).all()
        )
    assert len(consent_rows) > 0


@pytest.mark.asyncio
async def test_callback_refuses_new_account_without_terms_acceptance(
    client: AsyncClient,
    google_configured: None,
    migrated_database: None,
    google_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new Google account cannot be created without accepting the Terms."""
    _stub_google(
        monkeypatch,
        GoogleClaims(
            sub="sub-noterms",
            email="noterms@example.com",
            email_verified=True,
            name="No Terms",
        ),
    )
    client.cookies.set(
        OAUTH_STATE_COOKIE_NAME,
        await _seed_state(google_context["redis"], terms_accepted=False),
    )

    response = await client.get(
        "/v1/auth/google/callback?code=abc&state=known-state"
    )

    assert response.status_code == 400
    assert await _user_by_email("noterms@example.com") is None


@pytest.mark.asyncio
async def test_callback_auto_links_verified_email_to_existing_user(
    client: AsyncClient,
    google_configured: None,
    migrated_database: None,
    google_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verified Google email matching an account links instead of duplicating."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email="existing@example.com",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Existing User",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            session.add(UserRole(user_id=user.id, role="operator"))
        existing_id = user.id

    _stub_google(
        monkeypatch,
        GoogleClaims(
            sub="sub-existing",
            email="existing@example.com",
            email_verified=True,
            name="Existing User",
        ),
    )
    client.cookies.set(
        OAUTH_STATE_COOKIE_NAME, await _seed_state(google_context["redis"])
    )

    response = await client.get(
        "/v1/auth/google/callback?code=abc&state=known-state"
    )

    assert response.status_code == 302
    rows = await _oauth_rows()
    assert len(rows) == 1
    assert rows[0].user_id == existing_id
    # An already-onboarded user (has a role) is not sent back to onboarding.
    assert "/settings/onboarding" not in response.headers["location"]


@pytest.mark.asyncio
async def test_callback_with_totp_user_redirects_to_2fa_without_session(
    client: AsyncClient,
    google_configured: None,
    migrated_database: None,
    google_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 2FA user signing in with Google must clear TOTP before a session issues."""
    from app.modules.auth.service import _totp_challenge_key

    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email="secured@example.com",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Secured",
                email_verified=True,
                totp_enabled=True,
            )
            session.add(user)
            await session.flush()
            session.add(UserRole(user_id=user.id, role="operator"))
        secured_id = user.id

    _stub_google(
        monkeypatch,
        GoogleClaims(
            sub="sub-secured",
            email="secured@example.com",
            email_verified=True,
            name="Secured",
        ),
    )
    client.cookies.set(
        OAUTH_STATE_COOKIE_NAME, await _seed_state(google_context["redis"])
    )

    response = await client.get(
        "/v1/auth/google/callback?code=abc&state=known-state"
    )

    assert response.status_code == 302
    location = response.headers["location"]
    assert "/2fa-challenge" in location
    # No session is granted until the second factor is confirmed.
    assert response.cookies.get("refresh_token") is None

    challenge = location.split("challenge=", 1)[1].split("&", 1)[0]
    redis: FakeRedis = google_context["redis"]
    assert redis.values.get(_totp_challenge_key(challenge)) == str(secured_id)
    # The Google account was still linked despite the pending 2FA step.
    rows = await _oauth_rows()
    assert len(rows) == 1 and rows[0].user_id == secured_id


@pytest.mark.asyncio
async def test_callback_refuses_link_when_google_email_unverified(
    client: AsyncClient,
    google_configured: None,
    migrated_database: None,
    google_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unverified Google email must never auto-link to an existing account."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                User(
                    email="target@example.com",
                    password_hash=hash_password("CorrectHorse9"),
                    display_name="Target",
                    email_verified=True,
                )
            )

    _stub_google(
        monkeypatch,
        GoogleClaims(
            sub="sub-attacker",
            email="target@example.com",
            email_verified=False,
            name="Target",
        ),
    )
    client.cookies.set(
        OAUTH_STATE_COOKIE_NAME, await _seed_state(google_context["redis"])
    )

    response = await client.get(
        "/v1/auth/google/callback?code=abc&state=known-state"
    )

    assert response.status_code == 400
    assert await _oauth_rows() == []
