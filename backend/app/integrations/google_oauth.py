"""Google OAuth 2.0 authorization-code adapter for "Continue with Google".

We run the backend authorization-code flow with PKCE: build a consent URL
(this module), redirect the user to Google, then exchange the returned code
for tokens server-side and verify the id_token (build slice 2). The client
secret never leaves the server.

Google OpenID Connect endpoints:
  https://developers.google.com/identity/openid-connect/openid-connect

Maps to: Google Auth + Onboarding + 2FA design, build slice 1.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt  # type: ignore[import-untyped]

from app.core.config import Settings, get_settings

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
# Google issues id_tokens under either issuer string.
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
# OpenID Connect scopes: identity (openid) plus the verified email and basic
# profile we need to resolve or create the account.
GOOGLE_OAUTH_SCOPES = ("openid", "email", "profile")
# RFC 7636 allows a 43..128 char verifier; 64 random bytes -> 86 base64url chars.
_PKCE_VERIFIER_BYTES = 64
_GOOGLE_TIMEOUT_SECONDS = 15.0


class GoogleOAuthError(RuntimeError):
    """Raised when Google OAuth configuration or responses are invalid."""


@dataclass(frozen=True)
class GoogleClaims:
    """Normalized identity claims extracted from a verified Google id_token."""

    sub: str
    email: str
    email_verified: bool
    name: str | None


@dataclass(frozen=True)
class PkcePair:
    """A PKCE verifier and its derived S256 code challenge."""

    verifier: str
    challenge: str


def _b64url(payload: bytes) -> str:
    """Encode bytes as unpadded URL-safe base64 (RFC 7636 / OAuth convention)."""
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def generate_pkce_pair() -> PkcePair:
    """Generate a fresh PKCE verifier and its S256 challenge.

    Returns:
        A PkcePair whose challenge is the unpadded base64url SHA-256 of the
        verifier, suitable for ``code_challenge`` with ``code_challenge_method=S256``.
    """
    verifier = _b64url(secrets.token_bytes(_PKCE_VERIFIER_BYTES))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return PkcePair(verifier=verifier, challenge=challenge)


def generate_state() -> str:
    """Return a high-entropy, URL-safe CSRF state token."""
    return secrets.token_urlsafe(32)


def build_authorization_url(
    state: str,
    code_challenge: str,
    redirect_uri: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Build the Google consent URL for the authorization-code flow.

    Args:
        state: Opaque CSRF token echoed back to the callback for verification.
        code_challenge: S256 PKCE challenge derived from the stored verifier.
        redirect_uri: Per-request callback URL (one backend may serve several
            frontends); falls back to the configured GOOGLE_REDIRECT_URI.
        settings: Application settings (defaults to the process settings).

    Returns:
        The fully-formed Google authorization URL to redirect the user to.

    Raises:
        GoogleOAuthError: If Google client id or redirect URI are not configured.
    """
    resolved = settings or get_settings()
    effective_redirect_uri = redirect_uri or resolved.google_redirect_uri
    if not resolved.google_client_id or not effective_redirect_uri:
        raise GoogleOAuthError("Google OAuth is not configured.")

    params = {
        "client_id": resolved.google_client_id,
        "redirect_uri": effective_redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_OAUTH_SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        # Force the account chooser so a user can switch Google accounts; do not
        # request offline access — we mint our own session, not Google refresh.
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


async def exchange_code(
    code: str,
    code_verifier: str,
    redirect_uri: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens, server-side, with PKCE.

    Args:
        code: The authorization code returned by Google to the callback.
        code_verifier: The PKCE verifier sealed in the state cookie.
        redirect_uri: The same callback URL used at authorization (OAuth requires
            it to match); falls back to the configured GOOGLE_REDIRECT_URI.
        settings: Application settings (provides Google client config).

    Returns:
        The parsed token response (includes ``id_token``).

    Raises:
        GoogleOAuthError: If Google is not configured, the request fails, or
            Google returns a non-2xx response.
    """
    resolved = settings or get_settings()
    effective_redirect_uri = redirect_uri or resolved.google_redirect_uri
    if (
        not resolved.google_client_id
        or not resolved.google_client_secret
        or not effective_redirect_uri
    ):
        raise GoogleOAuthError("Google OAuth is not configured.")

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
        "client_id": resolved.google_client_id,
        "client_secret": resolved.google_client_secret.get_secret_value(),
        "redirect_uri": effective_redirect_uri,
    }
    try:
        async with httpx.AsyncClient(timeout=_GOOGLE_TIMEOUT_SECONDS) as http_client:
            response = await http_client.post(GOOGLE_TOKEN_ENDPOINT, data=data)
    except httpx.HTTPError as exc:
        raise GoogleOAuthError("Google token exchange failed.") from exc
    if response.status_code >= 400:
        # Google returns {"error": "...", "error_description": "..."}; surface it
        # so misconfig (invalid_client, redirect_uri_mismatch, invalid_grant) is
        # diagnosable. No secrets are present in this body.
        raise GoogleOAuthError(
            f"Google rejected the authorization code: {response.text}"
        )
    return dict(response.json())


async def fetch_google_jwks(settings: Settings | None = None) -> dict[str, Any]:
    """Fetch Google's current JSON Web Key Set for id_token verification."""
    try:
        async with httpx.AsyncClient(timeout=_GOOGLE_TIMEOUT_SECONDS) as http_client:
            response = await http_client.get(GOOGLE_JWKS_URI)
    except httpx.HTTPError as exc:
        raise GoogleOAuthError("Could not fetch Google signing keys.") from exc
    if response.status_code >= 400:
        raise GoogleOAuthError("Could not fetch Google signing keys.")
    return dict(response.json())


def verify_id_token(
    id_token: str,
    settings: Settings | None = None,
    jwks: dict[str, Any] | None = None,
) -> GoogleClaims:
    """Verify a Google id_token's signature and claims, returning identity.

    Validates the RS256 signature against Google's JWKS and checks the audience
    (our client id), issuer, and expiry before any claim is trusted.

    Args:
        id_token: The raw id_token JWT from the token exchange.
        settings: Application settings (provides the expected audience).
        jwks: Pre-fetched JWKS (used by callers/tests); required because
            verification is synchronous and key fetching is async.

    Returns:
        Normalized GoogleClaims (sub, email, email_verified, name).

    Raises:
        GoogleOAuthError: If Google is not configured, the signature/claims are
            invalid, or no JWKS was supplied.
    """
    resolved = settings or get_settings()
    if not resolved.google_client_id:
        raise GoogleOAuthError("Google OAuth is not configured.")
    if jwks is None:
        raise GoogleOAuthError("Google signing keys are required for verification.")

    try:
        claims = jwt.decode(
            id_token,
            jwks,
            algorithms=["RS256"],
            audience=resolved.google_client_id,
            issuer=GOOGLE_ISSUERS,
            # We only consume identity claims, not Google's access token, so there
            # is no token to hash-compare; skip the at_hash check (it otherwise
            # fails with "No access_token provided to compare against at_hash").
            options={"verify_at_hash": False},
        )
    except JWTError as exc:
        raise GoogleOAuthError(f"Invalid Google id_token: {exc}") from exc

    sub = claims.get("sub")
    email = claims.get("email")
    if not sub or not email:
        raise GoogleOAuthError("Google id_token is missing required claims.")
    return GoogleClaims(
        sub=str(sub),
        email=str(email),
        email_verified=bool(claims.get("email_verified", False)),
        name=claims.get("name"),
    )
