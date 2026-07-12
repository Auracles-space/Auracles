"""HTTP cookie helpers for browser refresh-token sessions and route hints."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Response

from app.core.config import Settings, get_settings

REFRESH_COOKIE_NAME = "refresh_token"
SESSION_HINT_COOKIE_NAME = "session_hint"
OAUTH_STATE_COOKIE_NAME = "oauth_state"
CONNECTOR_STATE_COOKIE_NAME = "auracles_connector_state"
REFRESH_COOKIE_MAX_AGE_SECONDS = 2_592_000
# The OAuth state cookie only has to survive the round trip to Google's consent
# screen and back, so it expires quickly to limit the replay window.
OAUTH_STATE_MAX_AGE_SECONDS = 600
CONNECTOR_STATE_MAX_AGE_SECONDS = 600
# Scoped to the integrations API so the connector cookie never rides along
# on unrelated requests.
CONNECTOR_STATE_COOKIE_PATH = "/v1/integrations"
# Root path so the cookie is sent under the frontend `/api` proxy prefix
# (`/api/v1/auth/refresh`) as well as direct `/v1/auth/refresh` in local dev.
# A narrower path scoped the cookie out of the proxied request and broke
# refresh in production (401 -> session bounce).
REFRESH_COOKIE_PATH = "/"
SESSION_HINT_COOKIE_PATH = "/"
OAUTH_STATE_COOKIE_PATH = "/"


def set_refresh_cookie(
    response: Response,
    token: str,
    settings: Settings | None = None,
    *,
    persistent: bool = False,
) -> None:
    """Attach an HttpOnly refresh-token cookie to a response.

    Args:
        response: The response to attach the cookie to.
        token: The opaque refresh-token value.
        settings: Optional settings override (injected in tests).
        persistent: When True (the "Remember me" checked path), the cookie
            carries a 30-day Max-Age so it survives browser restarts. When
            False, Max-Age is omitted, yielding a session cookie the browser
            drops on close.
    """
    resolved_settings = settings or get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=REFRESH_COOKIE_MAX_AGE_SECONDS if persistent else None,
        path=REFRESH_COOKIE_PATH,
        secure=resolved_settings.cookie_secure,
        httponly=True,
        samesite=resolved_settings.cookie_samesite,
    )


def _base64url_encode(payload: bytes) -> str:
    """Encode bytes as unpadded URL-safe base64."""
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _pad_b64url(value: str) -> bytes:
    """Restore base64 padding stripped by ``_base64url_encode`` for decoding."""
    return (value + "=" * (-len(value) % 4)).encode("ascii")


def _sign(value: str, settings: Settings) -> str:
    """Create an HMAC signature for a session-hint payload."""
    digest = hmac.new(
        settings.secret_key.get_secret_value().encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _base64url_encode(digest)


def create_session_hint_value(
    user_id: UUID,
    roles: list[str],
    totp_verified: bool,
    settings: Settings | None = None,
) -> str:
    """Create a signed, non-secret session hint payload for middleware routing."""
    resolved_settings = settings or get_settings()
    expires_at = datetime.now(UTC) + timedelta(seconds=REFRESH_COOKIE_MAX_AGE_SECONDS)
    payload = {
        "user_id": str(user_id),
        "roles": roles,
        "totp_verified": totp_verified,
        "exp": int(expires_at.timestamp()),
        "iat": datetime.now(UTC).timestamp(),
    }
    encoded = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{encoded}.{_sign(encoded, resolved_settings)}"


def set_session_hint_cookie(
    response: Response,
    user_id: UUID,
    roles: list[str],
    totp_verified: bool,
    settings: Settings | None = None,
    *,
    persistent: bool = False,
) -> None:
    """Attach a signed readable session-hint cookie for frontend routing only.

    The hint must share the refresh cookie's lifetime: pass the same
    ``persistent`` value used for ``set_refresh_cookie`` so a session-scoped
    login does not leave a longer-lived hint that desyncs the frontend guard.
    """
    resolved_settings = settings or get_settings()
    response.set_cookie(
        key=SESSION_HINT_COOKIE_NAME,
        value=create_session_hint_value(
            user_id=user_id,
            roles=roles,
            totp_verified=totp_verified,
            settings=resolved_settings,
        ),
        max_age=REFRESH_COOKIE_MAX_AGE_SECONDS if persistent else None,
        path=SESSION_HINT_COOKIE_PATH,
        secure=resolved_settings.cookie_secure,
        httponly=False,
        samesite=resolved_settings.cookie_samesite,
    )


def create_oauth_state_value(
    state: str,
    verifier: str,
    next_path: str | None,
    terms_accepted: bool = False,
    redirect_uri: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Create a signed, HttpOnly OAuth state payload for CSRF + PKCE.

    Carries the CSRF ``state`` token, the PKCE ``verifier`` (needed to redeem the
    authorization code at the callback), the optional post-login ``next`` path,
    and whether the user accepted the Terms at sign-up. Signed with SECRET_KEY so
    a tampered value is rejected; HttpOnly so neither the PKCE verifier nor the
    consent flag is readable or forgeable by client JavaScript.

    Args:
        state: CSRF state token also sent to Google.
        verifier: PKCE code verifier whose S256 challenge was sent to Google.
        next_path: Optional in-app path to resume after sign-in.
        terms_accepted: Whether the user accepted the Terms before starting.
        settings: Application settings (defaults to the process settings).

    Returns:
        A ``<base64url-json>.<signature>`` string for the cookie value.
    """
    resolved_settings = settings or get_settings()
    expires_at = datetime.now(UTC) + timedelta(seconds=OAUTH_STATE_MAX_AGE_SECONDS)
    payload = {
        "state": state,
        "verifier": verifier,
        "next": next_path,
        "terms_accepted": terms_accepted,
        "redirect_uri": redirect_uri,
        "exp": int(expires_at.timestamp()),
    }
    encoded = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{encoded}.{_sign(encoded, resolved_settings)}"


def read_oauth_state_value(
    raw: str | None,
    settings: Settings | None = None,
) -> dict[str, object] | None:
    """Verify and decode an OAuth state cookie value.

    Args:
        raw: The cookie value, or None if the cookie was absent.
        settings: Application settings (defaults to the process settings).

    Returns:
        The decoded payload dict, or None if the value is missing, malformed,
        signature-invalid, or expired.
    """
    if not raw or "." not in raw:
        return None
    resolved_settings = settings or get_settings()
    encoded, _, signature = raw.rpartition(".")
    expected = _sign(encoded, resolved_settings)
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(_pad_b64url(encoded)))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(datetime.now(UTC).timestamp()):
        return None
    return payload


def set_oauth_state_cookie(
    response: Response,
    state: str,
    verifier: str,
    next_path: str | None,
    terms_accepted: bool = False,
    redirect_uri: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Attach the signed HttpOnly OAuth state cookie for the consent round trip."""
    resolved_settings = settings or get_settings()
    response.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=create_oauth_state_value(
            state=state,
            verifier=verifier,
            next_path=next_path,
            terms_accepted=terms_accepted,
            redirect_uri=redirect_uri,
            settings=resolved_settings,
        ),
        max_age=OAUTH_STATE_MAX_AGE_SECONDS,
        path=OAUTH_STATE_COOKIE_PATH,
        secure=resolved_settings.cookie_secure,
        httponly=True,
        samesite=resolved_settings.cookie_samesite,
    )


def clear_oauth_state_cookie(
    response: Response,
    settings: Settings | None = None,
) -> None:
    """Clear the OAuth state cookie once the consent round trip completes."""
    resolved_settings = settings or get_settings()
    response.delete_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        path=OAUTH_STATE_COOKIE_PATH,
        secure=resolved_settings.cookie_secure,
        httponly=True,
        samesite=resolved_settings.cookie_samesite,
    )


def create_connector_state_value(
    *,
    state: str,
    verifier: str,
    user_id: str,
    settings: Settings | None = None,
) -> str:
    """Create a signed connector OAuth state payload.

    Carries the CSRF ``state``, the PKCE ``verifier``, and the initiating
    ``user_id`` — the provider callback arrives as an unauthenticated
    browser redirect, so the cookie is what binds the grant back to the
    signed-in contributor. Signed with SECRET_KEY; a tampered value is
    rejected at read time.
    """
    resolved_settings = settings or get_settings()
    expires_at = datetime.now(UTC) + timedelta(
        seconds=CONNECTOR_STATE_MAX_AGE_SECONDS
    )
    payload = {
        "state": state,
        "verifier": verifier,
        "user_id": user_id,
        "exp": int(expires_at.timestamp()),
    }
    encoded = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{encoded}.{_sign(encoded, resolved_settings)}"


def set_connector_state_cookie(
    response: Response,
    *,
    state: str,
    verifier: str,
    user_id: str,
    settings: Settings | None = None,
) -> None:
    """Attach the signed HttpOnly connector OAuth state cookie."""
    resolved_settings = settings or get_settings()
    response.set_cookie(
        key=CONNECTOR_STATE_COOKIE_NAME,
        value=create_connector_state_value(
            state=state,
            verifier=verifier,
            user_id=user_id,
            settings=resolved_settings,
        ),
        max_age=CONNECTOR_STATE_MAX_AGE_SECONDS,
        path=CONNECTOR_STATE_COOKIE_PATH,
        secure=resolved_settings.cookie_secure,
        httponly=True,
        samesite=resolved_settings.cookie_samesite,
    )


def read_connector_state_value(
    raw: str | None,
    settings: Settings | None = None,
) -> dict[str, object] | None:
    """Verify and decode a connector state cookie value.

    Returns:
        The decoded payload dict, or None if the value is missing,
        malformed, signature-invalid, or expired.
    """
    if not raw or "." not in raw:
        return None
    resolved_settings = settings or get_settings()
    encoded, _, signature = raw.rpartition(".")
    if not hmac.compare_digest(signature, _sign(encoded, resolved_settings)):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(_pad_b64url(encoded)))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(datetime.now(UTC).timestamp()):
        return None
    return payload


def clear_connector_state_cookie(
    response: Response,
    settings: Settings | None = None,
) -> None:
    """Clear the connector state cookie once the consent round trip completes."""
    resolved_settings = settings or get_settings()
    response.delete_cookie(
        key=CONNECTOR_STATE_COOKIE_NAME,
        path=CONNECTOR_STATE_COOKIE_PATH,
        secure=resolved_settings.cookie_secure,
        httponly=True,
        samesite=resolved_settings.cookie_samesite,
    )


def clear_refresh_cookie(response: Response, settings: Settings | None = None) -> None:
    """Clear the browser refresh-token cookie.

    Must use the same SameSite attribute as the original Set-Cookie call;
    browsers ignore deletion when SameSite mismatches, leaving stale tokens
    behind under cross-site (SameSite=None) deployments.
    """
    resolved_settings = settings or get_settings()
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        secure=resolved_settings.cookie_secure,
        httponly=True,
        samesite=resolved_settings.cookie_samesite,
    )


def clear_session_hint_cookie(
    response: Response,
    settings: Settings | None = None,
) -> None:
    """Clear the browser session-hint cookie.

    Must use the same SameSite attribute as the original Set-Cookie call;
    browsers ignore deletion when SameSite mismatches.
    """
    resolved_settings = settings or get_settings()
    response.delete_cookie(
        key=SESSION_HINT_COOKIE_NAME,
        path=SESSION_HINT_COOKIE_PATH,
        secure=resolved_settings.cookie_secure,
        httponly=False,
        samesite=resolved_settings.cookie_samesite,
    )
