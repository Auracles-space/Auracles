"""Authenticated multiplexed WebSocket gateway for realtime Project updates."""

from __future__ import annotations

import contextlib
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

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


async def _project_membership_checker(project_id: UUID, user_id: UUID) -> bool:
    """Return whether a user can subscribe to one Project channel."""
    async with async_session_factory() as db:
        return await is_project_member(db, project_id=project_id, user_id=user_id)


async def _authenticate(websocket: WebSocket) -> User | None:
    """Perform the first-message auth handshake for one WebSocket."""
    await websocket.send_json({"type": "auth_required"})
    try:
        message = await websocket.receive_json()
    except WebSocketDisconnect:
        return None
    if not isinstance(message, dict) or message.get("type") != "auth":
        await websocket.send_json(
            {"type": "error", "error_code": "auth_required"},
        )
        await websocket.close(code=1008)
        return None
    token = message.get("token")
    if not isinstance(token, str) or not token.strip():
        await websocket.send_json(
            {"type": "error", "error_code": "invalid_token"},
        )
        await websocket.close(code=1008)
        return None

    async with async_session_factory() as db:
        user = await authenticate_websocket_token(db, token)
    if user is None:
        await websocket.send_json(
            {"type": "error", "error_code": "invalid_token"},
        )
        await websocket.close(code=1008)
        return None
    await websocket.send_json({"type": "auth_ok", "user_id": str(user.id)})
    return user


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
    user = await _authenticate(websocket)
    if user is None:
        return

    subscriptions: dict[str, SubscriptionHandle] = {}
    log = logger.bind(module="realtime", action="websocket_gateway", user_id=user.id)
    try:
        while True:
            message = await websocket.receive_json()
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
        await _close_subscriptions(subscriptions)
