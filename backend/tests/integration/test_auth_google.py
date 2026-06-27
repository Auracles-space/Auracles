"""Integration tests for the Google sign-in start endpoint.

Slice 1 covers only ``GET /v1/auth/google/start``: build the consent redirect,
plant the signed HttpOnly state cookie (CSRF + PKCE verifier), and refuse when
Google is not configured. The callback lands in slice 2.

Maps to: Google Auth + Onboarding + 2FA design, build slice 1.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from app.core.config import Settings, get_settings
from app.core.cookies import OAUTH_STATE_COOKIE_NAME, read_oauth_state_value
from app.integrations.google_oauth import GOOGLE_AUTHORIZATION_ENDPOINT
from app.main import app

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
