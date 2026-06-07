"""HTTP cookie helpers for browser refresh-token sessions."""

from fastapi import Response

from app.core.config import Settings, get_settings

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_MAX_AGE_SECONDS = 2_592_000
REFRESH_COOKIE_PATH = "/v1/auth"


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


def clear_refresh_cookie(response: Response) -> None:
    """Clear the browser refresh-token cookie."""
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )
