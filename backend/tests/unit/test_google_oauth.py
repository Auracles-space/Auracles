"""Tests for the Google OAuth authorization-code adapter.

Covers PKCE generation and authorization-URL construction for the
"Continue with Google" sign-in flow (backend authorization-code flow). Code
exchange and id_token verification land in build slice 2.

Maps to: Google Auth + Onboarding + 2FA design, build slice 1.
"""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.config import Settings
from app.integrations.google_oauth import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GoogleOAuthError,
    build_authorization_url,
    generate_pkce_pair,
)

GOOGLE_SETTINGS = Settings(
    GOOGLE_CLIENT_ID="client-abc.apps.googleusercontent.com",
    GOOGLE_CLIENT_SECRET="gclient_secret",
    GOOGLE_REDIRECT_URI="https://auracles.space/v1/auth/google/callback",
)


def test_generate_pkce_pair_produces_s256_challenge() -> None:
    """The challenge is the unpadded base64url SHA-256 of the verifier (RFC 7636)."""
    pair = generate_pkce_pair()

    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(pair.verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    assert pair.challenge == expected
    assert pair.verifier != pair.challenge
    # RFC 7636 bounds the verifier length to 43..128 characters.
    assert 43 <= len(pair.verifier) <= 128


def test_generate_pkce_pair_is_unique_per_call() -> None:
    """Each authorization attempt gets a fresh, unguessable verifier."""
    assert generate_pkce_pair().verifier != generate_pkce_pair().verifier


def test_build_authorization_url_contains_required_oauth_params() -> None:
    """The auth URL carries client, redirect, PKCE challenge, state, and scope."""
    url = build_authorization_url(
        state="state-token",
        code_challenge="challenge-token",
        settings=GOOGLE_SETTINGS,
    )

    split = urlsplit(url)
    assert (
        f"{split.scheme}://{split.netloc}{split.path}" == GOOGLE_AUTHORIZATION_ENDPOINT
    )
    params = parse_qs(split.query)
    assert params["client_id"] == ["client-abc.apps.googleusercontent.com"]
    assert params["redirect_uri"] == [
        "https://auracles.space/v1/auth/google/callback"
    ]
    assert params["response_type"] == ["code"]
    assert "openid" in params["scope"][0]
    assert "email" in params["scope"][0]
    assert params["state"] == ["state-token"]
    assert params["code_challenge"] == ["challenge-token"]
    assert params["code_challenge_method"] == ["S256"]


def test_build_authorization_url_requires_configured_client() -> None:
    """Without Google credentials the adapter refuses rather than build a bad URL."""
    with pytest.raises(GoogleOAuthError):
        build_authorization_url(
            state="s",
            code_challenge="c",
            settings=Settings(),
        )
