"""Unit tests for refresh + session-hint cookie helpers.

Covers Phase 1 deployment fix: clear-cookie helpers must echo the runtime
`COOKIE_SAMESITE` value so browsers honor cookie deletion under cross-site
(SameSite=None) deployments — for example, Render + Vercel where the API
and frontend live on different eTLD+1 domains.
"""

from __future__ import annotations

from fastapi import Response

from app.core.config import Settings
from app.core.cookies import (
    REFRESH_COOKIE_NAME,
    SESSION_HINT_COOKIE_NAME,
    clear_refresh_cookie,
    clear_session_hint_cookie,
    set_refresh_cookie,
)


def _cookie_header(response: Response, cookie_name: str) -> str:
    """Return the Set-Cookie header for a given cookie name."""
    return next(
        header
        for key, header in response.raw_headers
        if key == b"set-cookie" and header.decode("ascii").startswith(f"{cookie_name}=")
    ).decode("ascii")


def test_set_refresh_cookie_uses_runtime_samesite_none() -> None:
    """`set_refresh_cookie` writes SameSite=None when runtime config says so."""
    settings = Settings(
        ENVIRONMENT="local",
        COOKIE_SAMESITE="none",
    )
    response = Response()

    set_refresh_cookie(response, "token-value", settings=settings)

    header = _cookie_header(response, REFRESH_COOKIE_NAME)
    assert "samesite=none" in header.lower()
    assert "httponly" in header.lower()
    assert "secure" in header.lower()


def test_clear_refresh_cookie_echoes_samesite_none() -> None:
    """`clear_refresh_cookie` must match original SameSite or browsers ignore delete."""
    settings = Settings(
        ENVIRONMENT="local",
        COOKIE_SAMESITE="none",
    )
    response = Response()

    clear_refresh_cookie(response, settings=settings)

    header = _cookie_header(response, REFRESH_COOKIE_NAME)
    assert "samesite=none" in header.lower()
    assert "httponly" in header.lower()
    assert "secure" in header.lower()
    assert "max-age=0" in header.lower()


def test_clear_refresh_cookie_defaults_to_strict_in_local() -> None:
    """Local deployments keep SameSite=Strict and clear with the same attribute."""
    settings = Settings(ENVIRONMENT="local")
    response = Response()

    clear_refresh_cookie(response, settings=settings)

    header = _cookie_header(response, REFRESH_COOKIE_NAME)
    assert "samesite=strict" in header.lower()


def test_clear_session_hint_cookie_echoes_samesite_none() -> None:
    """`clear_session_hint_cookie` mirrors runtime SameSite so deletion sticks."""
    settings = Settings(
        ENVIRONMENT="local",
        COOKIE_SAMESITE="none",
    )
    response = Response()

    clear_session_hint_cookie(response, settings=settings)

    header = _cookie_header(response, SESSION_HINT_COOKIE_NAME)
    assert "samesite=none" in header.lower()
    assert "secure" in header.lower()
    assert "httponly" not in header.lower()
    assert "max-age=0" in header.lower()


def test_clear_session_hint_cookie_defaults_to_strict() -> None:
    """Default deployment leaves session_hint with SameSite=Strict on clear."""
    settings = Settings(ENVIRONMENT="local")
    response = Response()

    clear_session_hint_cookie(response, settings=settings)

    header = _cookie_header(response, SESSION_HINT_COOKIE_NAME)
    assert "samesite=strict" in header.lower()
