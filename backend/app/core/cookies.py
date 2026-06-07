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
REFRESH_COOKIE_MAX_AGE_SECONDS = 2_592_000
REFRESH_COOKIE_PATH = "/v1/auth"
SESSION_HINT_COOKIE_PATH = "/"


def set_refresh_cookie(
    response: Response,
    token: str,
    settings: Settings | None = None,
) -> None:
    """Attach an HttpOnly refresh-token cookie to a response."""
    resolved_settings = settings or get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=REFRESH_COOKIE_MAX_AGE_SECONDS,
        path=REFRESH_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite=resolved_settings.cookie_samesite,
    )


def _base64url_encode(payload: bytes) -> str:
    """Encode bytes as unpadded URL-safe base64."""
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _sign(value: str, settings: Settings) -> str:
    """Create an HMAC signature for a session-hint payload."""
    digest = hmac.new(
        settings.secret_key.encode("utf-8"),
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
) -> None:
    """Attach a signed readable session-hint cookie for frontend routing only."""
    resolved_settings = settings or get_settings()
    response.set_cookie(
        key=SESSION_HINT_COOKIE_NAME,
        value=create_session_hint_value(
            user_id=user_id,
            roles=roles,
            totp_verified=totp_verified,
            settings=resolved_settings,
        ),
        max_age=REFRESH_COOKIE_MAX_AGE_SECONDS,
        path=SESSION_HINT_COOKIE_PATH,
        secure=True,
        httponly=False,
        samesite=resolved_settings.cookie_samesite,
    )


def clear_refresh_cookie(response: Response) -> None:
    """Clear the browser refresh-token cookie."""
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )


def clear_session_hint_cookie(response: Response) -> None:
    """Clear the browser session-hint cookie."""
    response.delete_cookie(
        key=SESSION_HINT_COOKIE_NAME,
        path=SESSION_HINT_COOKIE_PATH,
        secure=True,
        httponly=False,
        samesite="strict",
    )
