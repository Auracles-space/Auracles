"""Realtime authentication helpers for first-message WebSocket handshakes."""

from __future__ import annotations

from jose import JWTError  # type: ignore[import-untyped]
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.shared.schemas.token import TokenPayload


async def authenticate_websocket_token(
    db: AsyncSession,
    token: str,
) -> tuple[User, TokenPayload] | None:
    """Return the authenticated user and token claims, or None.

    Re-runnable mid-session: the gateway calls this on every inbound message so
    an expired token, revoked session, or suspended/deactivated account tears
    the socket down rather than leaving a long-lived connection authorized off a
    stale handshake.
    """
    try:
        payload = decode_access_token(token)
    except (JWTError, ValidationError):
        return None
    user = await db.scalar(select(User).where(User.id == payload.sub))
    if user is None or user.deactivated_at is not None or user.suspended_at is not None:
        return None
    if auth_service.is_access_token_revoked_for_user(user, payload):
        return None
    return user, payload
