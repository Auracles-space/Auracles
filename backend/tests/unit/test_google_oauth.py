"""Tests for the Google OAuth authorization-code adapter.

Covers PKCE generation and authorization-URL construction for the
"Continue with Google" sign-in flow (backend authorization-code flow). Code
exchange and id_token verification land in build slice 2.

Maps to: Google Auth + Onboarding + 2FA design, build slice 1.
"""

from __future__ import annotations

import base64
import hashlib
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt

from app.core.config import Settings
from app.integrations.google_oauth import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GOOGLE_TOKEN_ENDPOINT,
    GoogleOAuthError,
    build_authorization_url,
    exchange_code,
    generate_pkce_pair,
    verify_id_token,
)

GOOGLE_SETTINGS = Settings(
    GOOGLE_CLIENT_ID="client-abc.apps.googleusercontent.com",
    GOOGLE_CLIENT_SECRET="gclient_secret",
    GOOGLE_REDIRECT_URI="https://auracles.space/v1/auth/google/callback",
)


def _rsa_keypair() -> tuple[str, dict[str, object]]:
    """Return (private PEM, single-key JWKS) for signing and verifying id_tokens."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    jwk_dict = jwk.construct(public_pem, "RS256").to_dict()
    jwk_dict["kid"] = "k1"
    return private_pem, {"keys": [jwk_dict]}


def _id_token(private_pem: str, **overrides: object) -> str:
    """Sign a Google-style id_token with sensible defaults, overridable per test."""
    claims: dict[str, object] = {
        "iss": "https://accounts.google.com",
        "aud": "client-abc.apps.googleusercontent.com",
        "sub": "google-sub-123",
        "email": "mara@example.com",
        "email_verified": True,
        "name": "Mara Okafor",
        "exp": int(time.time()) + 600,
        "iat": int(time.time()),
    }
    claims.update(overrides)
    return jwt.encode(
        claims, private_pem, algorithm="RS256", headers={"kid": "k1"}
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


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_posts_pkce_verifier_and_returns_tokens() -> None:
    """Code exchange sends the secret + PKCE verifier server-side and returns tokens."""
    route = respx.post(GOOGLE_TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"id_token": "the-id-token"})
    )

    tokens = await exchange_code(
        code="auth-code",
        code_verifier="pkce-verifier",
        settings=GOOGLE_SETTINGS,
    )

    assert tokens["id_token"] == "the-id-token"
    sent = dict(parse_qs(route.calls.last.request.content.decode()))
    assert sent["grant_type"] == ["authorization_code"]
    assert sent["code"] == ["auth-code"]
    assert sent["code_verifier"] == ["pkce-verifier"]
    assert sent["client_id"] == ["client-abc.apps.googleusercontent.com"]
    assert sent["client_secret"] == ["gclient_secret"]
    assert sent["redirect_uri"] == [
        "https://auracles.space/v1/auth/google/callback"
    ]


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_raises_on_provider_error() -> None:
    """A non-2xx token response surfaces as a typed provider error."""
    respx.post(GOOGLE_TOKEN_ENDPOINT).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )

    with pytest.raises(GoogleOAuthError):
        await exchange_code(
            code="bad", code_verifier="v", settings=GOOGLE_SETTINGS
        )


def test_verify_id_token_accepts_valid_signature_and_returns_claims() -> None:
    """A correctly signed token for our audience yields normalized claims."""
    private_pem, jwks = _rsa_keypair()
    token = _id_token(private_pem)

    claims = verify_id_token(token, settings=GOOGLE_SETTINGS, jwks=jwks)

    assert claims.sub == "google-sub-123"
    assert claims.email == "mara@example.com"
    assert claims.email_verified is True
    assert claims.name == "Mara Okafor"


def test_verify_id_token_rejects_wrong_audience() -> None:
    """A token minted for a different client id is rejected."""
    private_pem, jwks = _rsa_keypair()
    token = _id_token(private_pem, aud="someone-else.apps.googleusercontent.com")

    with pytest.raises(GoogleOAuthError):
        verify_id_token(token, settings=GOOGLE_SETTINGS, jwks=jwks)


def test_verify_id_token_rejects_expired_token() -> None:
    """An expired token is rejected even with a valid signature."""
    private_pem, jwks = _rsa_keypair()
    token = _id_token(private_pem, exp=int(time.time()) - 10)

    with pytest.raises(GoogleOAuthError):
        verify_id_token(token, settings=GOOGLE_SETTINGS, jwks=jwks)


def test_verify_id_token_rejects_foreign_signature() -> None:
    """A token signed by an unrelated key (not in our JWKS) is rejected."""
    attacker_pem, _ = _rsa_keypair()
    _, our_jwks = _rsa_keypair()
    token = _id_token(attacker_pem)

    with pytest.raises(GoogleOAuthError):
        verify_id_token(token, settings=GOOGLE_SETTINGS, jwks=our_jwks)
