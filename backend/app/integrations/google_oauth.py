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
from urllib.parse import urlencode

from app.core.config import Settings, get_settings

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
# OpenID Connect scopes: identity (openid) plus the verified email and basic
# profile we need to resolve or create the account.
GOOGLE_OAUTH_SCOPES = ("openid", "email", "profile")
# RFC 7636 allows a 43..128 char verifier; 64 random bytes -> 86 base64url chars.
_PKCE_VERIFIER_BYTES = 64


class GoogleOAuthError(RuntimeError):
    """Raised when Google OAuth configuration or responses are invalid."""


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
    settings: Settings | None = None,
) -> str:
    """Build the Google consent URL for the authorization-code flow.

    Args:
        state: Opaque CSRF token echoed back to the callback for verification.
        code_challenge: S256 PKCE challenge derived from the stored verifier.
        settings: Application settings (defaults to the process settings).

    Returns:
        The fully-formed Google authorization URL to redirect the user to.

    Raises:
        GoogleOAuthError: If Google client id or redirect URI are not configured.
    """
    resolved = settings or get_settings()
    if not resolved.google_client_id or not resolved.google_redirect_uri:
        raise GoogleOAuthError("Google OAuth is not configured.")

    params = {
        "client_id": resolved.google_client_id,
        "redirect_uri": resolved.google_redirect_uri,
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
