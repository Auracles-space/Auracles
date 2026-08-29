"""Authenticated multiplexed WebSocket gateway for realtime Project updates."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from time import monotonic
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.modules.auth.models import User
from app.modules.realtime.auth import authenticate_websocket_token
from app.modules.realtime.channels import (
    ChannelResolutionError,
    can_subscribe_to_channel,
)
from app.modules.realtime.pubsub import (
    RealtimeEvent,
    SubscriptionHandle,
    subscribe_channel,
)
from app.modules.workspace.service import is_project_member

router = APIRouter(tags=["Realtime"])
_settings = get_settings()

AUTH_HANDSHAKE_TIMEOUT_SECONDS = 5.0
WS_AUTH_CLOSE_CODE = 4401
# Mirrors HTTP 429 in the application close-code range: the socket was well
# formed and authenticated, it simply exceeded a resource cap.
WS_POLICY_CLOSE_CODE = 4429

WS_MAX_CONNECTIONS_PER_USER = _settings.ws_max_connections_per_user
WS_MAX_MESSAGES_PER_SECOND = _settings.ws_max_messages_per_second
WS_MAX_SUBSCRIPTIONS_PER_SOCKET = _settings.ws_max_subscriptions_per_socket

# Live socket count per user, scoped to this process. Deliberately not shared
# through Redis: the resources at risk (this worker's DB pool and memory) are
# per process, and a process-local tally cannot outlive the process that owns
# it. A Redis tally would need heartbeats to avoid leaking counts when a worker
# dies mid-connection, and a leaked count locks a user out of their own
# realtime feed until it is cleared by hand.
_active_connections: dict[UUID, int] = {}


def active_connection_count(user_id: UUID) -> int:
    """Return this process's live socket count for one user."""
    return _active_connections.get(user_id, 0)


def _register_connection(user_id: UUID) -> bool:
    """Claim a connection slot, returning False when the user is at their cap."""
    current = _active_connections.get(user_id, 0)
    if current >= WS_MAX_CONNECTIONS_PER_USER:
        return False
    _active_connections[user_id] = current + 1
    return True


def _release_connection(user_id: UUID) -> None:
    """Return a connection slot once its socket has closed."""
    remaining = _active_connections.get(user_id, 0) - 1
    if remaining > 0:
        _active_connections[user_id] = remaining
    else:
        _active_connections.pop(user_id, None)


class _MessageRateLimiter:
    """Fixed-window inbound message limiter for a single socket.

    Deliberately in-process and allocation-free. The cap exists to stop a
    message flood from opening one DB session per message, so consulting Redis
    to enforce it would reintroduce the very per-message round trip it is
    meant to prevent.
    """

    def __init__(self, limit: int) -> None:
        """Configure the per-second message allowance for one socket."""
        self._limit = limit
        self._window_started = 0.0
        self._count = 0

    def allow(self) -> bool:
        """Record one inbound message, returning False once the budget is spent."""
        # Monotonic, so a clock adjustment cannot widen or freeze the window.
        now = monotonic()
        if now - self._window_started >= 1.0:
            self._window_started = now
            self._count = 0
        self._count += 1
        return self._count <= self._limit


async def _project_membership_checker(project_id: UUID, user_id: UUID) -> bool:
    """Return whether a user can subscribe to one Project channel."""
    async with async_session_factory() as db:
        return await is_project_member(db, project_id=project_id, user_id=user_id)


async def _authenticate(websocket: WebSocket) -> tuple[User, str, int] | None:
    """Perform the first-message auth handshake for one WebSocket.

    Returns the authenticated user, the raw access token (kept for per-message
    re-validation), and the token's expiry epoch seconds, or None when the
    handshake fails and the socket has already been closed.
    """
    await websocket.send_json({"type": "auth_required"})
    try:
        message = await asyncio.wait_for(
            websocket.receive_json(),
            timeout=AUTH_HANDSHAKE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        await websocket.send_json(
            {"type": "error", "error_code": "auth_timeout"},
        )
        await websocket.close(code=WS_AUTH_CLOSE_CODE)
        return None
    except WebSocketDisconnect:
        return None
    if not isinstance(message, dict) or message.get("type") != "auth":
        await websocket.send_json(
            {"type": "error", "error_code": "auth_required"},
        )
        await websocket.close(code=WS_AUTH_CLOSE_CODE)
        return None
    token = message.get("token")
    if not isinstance(token, str) or not token.strip():
        await websocket.send_json(
            {"type": "error", "error_code": "invalid_token"},
        )
        await websocket.close(code=WS_AUTH_CLOSE_CODE)
        return None

    async with async_session_factory() as db:
        authenticated = await authenticate_websocket_token(db, token)
    if authenticated is None:
        await websocket.send_json(
            {"type": "error", "error_code": "invalid_token"},
        )
        await websocket.close(code=WS_AUTH_CLOSE_CODE)
        return None
    user, payload = authenticated
    await websocket.send_json({"type": "auth_ok", "user_id": str(user.id)})
    return user, token, payload.exp


async def _session_still_valid(token: str) -> bool:
    """Re-check token expiry, revocation, and account status mid-session."""
    async with async_session_factory() as db:
        return await authenticate_websocket_token(db, token) is not None


async def _subscribe(
    *,
    websocket: WebSocket,
    user: User,
    channel: str,
    subscriptions: dict[str, SubscriptionHandle],
) -> None:
    """Authorize and subscribe the socket to one public channel."""
    try:
        allowed = await can_subscribe_to_channel(
            channel,
            user.id,
            project_membership_checker=_project_membership_checker,
        )
    except ChannelResolutionError:
        await websocket.send_json(
            {"type": "error", "error_code": "invalid_channel", "channel": channel},
        )
        return
    if not allowed:
        await websocket.send_json(
            {
                "type": "error",
                "error_code": "subscription_denied",
                "channel": channel,
            }
        )
        return
    if channel in subscriptions:
        await websocket.send_json({"type": "subscribed", "channel": channel})
        return
    if len(subscriptions) >= WS_MAX_SUBSCRIPTIONS_PER_SOCKET:
        # Each subscription holds a broker handle for the socket's lifetime.
        # Refuse the extra channel but leave the socket open: a client asking
        # for too many channels is over-eager, not hostile, and the ones it
        # already holds keep working.
        await websocket.send_json(
            {
                "type": "error",
                "error_code": "subscription_limit",
                "channel": channel,
            }
        )
        return

    async def forward_event(event: RealtimeEvent) -> None:
        """Forward one pub/sub event to this WebSocket."""
        await websocket.send_json(event)

    subscriptions[channel] = await subscribe_channel(channel, forward_event)
    await websocket.send_json({"type": "subscribed", "channel": channel})


async def _unsubscribe(
    *,
    websocket: WebSocket,
    channel: str,
    subscriptions: dict[str, SubscriptionHandle],
) -> None:
    """Unsubscribe the socket from one channel."""
    handle = subscriptions.pop(channel, None)
    if handle is not None:
        await handle.close()
    await websocket.send_json({"type": "unsubscribed", "channel": channel})


async def _close_subscriptions(subscriptions: dict[str, SubscriptionHandle]) -> None:
    """Close all active channel subscriptions for one socket."""
    for handle in list(subscriptions.values()):
        with contextlib.suppress(Exception):
            await handle.close()
    subscriptions.clear()


@router.websocket("/ws")
async def websocket_gateway(websocket: WebSocket) -> None:
    """Serve the global authenticated realtime WebSocket endpoint."""
    await websocket.accept()
    authenticated = await _authenticate(websocket)
    if authenticated is None:
        return
    user, token, token_exp = authenticated

    subscriptions: dict[str, SubscriptionHandle] = {}
    log = logger.bind(module="realtime", action="websocket_gateway", user_id=user.id)

    if not _register_connection(user.id):
        log.warning("websocket_connection_limit_exceeded")
        await websocket.send_json(
            {"type": "error", "error_code": "connection_limit"},
        )
        await websocket.close(code=WS_POLICY_CLOSE_CODE)
        return

    rate_limiter = _MessageRateLimiter(WS_MAX_MESSAGES_PER_SECOND)
    try:
        while True:
            remaining = token_exp - datetime.now(UTC).timestamp()
            if remaining <= 0:
                await websocket.send_json(
                    {"type": "error", "error_code": "token_expired"},
                )
                await websocket.close(code=WS_AUTH_CLOSE_CODE)
                break
            try:
                # Idle sockets are torn down when the access token expires.
                message = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=remaining,
                )
            except TimeoutError:
                await websocket.send_json(
                    {"type": "error", "error_code": "token_expired"},
                )
                await websocket.close(code=WS_AUTH_CLOSE_CODE)
                break
            # Metered before the session re-check below, which opens a DB
            # session per message. Shedding here is what keeps a flood off the
            # connection pool; letting it through and erroring afterwards
            # would already have paid the cost being defended against.
            if not rate_limiter.allow():
                log.warning("websocket_rate_limited")
                await websocket.send_json(
                    {"type": "error", "error_code": "rate_limited"},
                )
                await websocket.close(code=WS_POLICY_CLOSE_CODE)
                break
            # Re-validate each message so revocation/suspension ends the session.
            if not await _session_still_valid(token):
                await websocket.send_json(
                    {"type": "error", "error_code": "session_revoked"},
                )
                await websocket.close(code=WS_AUTH_CLOSE_CODE)
                break
            if not isinstance(message, dict):
                await websocket.send_json(
                    {"type": "error", "error_code": "invalid_message"},
                )
                continue
            message_type = message.get("type")
            channel = message.get("channel")
            if message_type in {"subscribe", "unsubscribe"} and not isinstance(
                channel,
                str,
            ):
                await websocket.send_json(
                    {"type": "error", "error_code": "invalid_channel"},
                )
                continue
            if message_type == "subscribe":
                assert isinstance(channel, str)
                await _subscribe(
                    websocket=websocket,
                    user=user,
                    channel=channel,
                    subscriptions=subscriptions,
                )
            elif message_type == "unsubscribe":
                assert isinstance(channel, str)
                await _unsubscribe(
                    websocket=websocket,
                    channel=channel,
                    subscriptions=subscriptions,
                )
            elif message_type == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json(
                    {"type": "error", "error_code": "unknown_message_type"},
                )
    except WebSocketDisconnect:
        log.info("websocket_disconnected")
    except Exception as exc:
        log.error("websocket_failed", error=str(exc))
        raise
    finally:
        _release_connection(user.id)
        await _close_subscriptions(subscriptions)
