"""Redis-backed realtime pub/sub primitives.

This module is deliberately transport-agnostic: it publishes typed event
envelopes to Redis and lets callers subscribe a handler to a public channel.
The WebSocket gateway added later is responsible for turning those events into
socket frames.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Any, Self

from loguru import logger
from redis.asyncio.client import PubSub

from app.core.redis import get_redis

type RealtimeEvent = dict[str, Any]
type RealtimeHandler = Callable[[RealtimeEvent], None | Awaitable[None]]

REDIS_CHANNEL_PREFIX = "auracles:ws:"


@dataclass
class SubscriptionHandle:
    """Manage a running Redis pub/sub listener task."""

    channel: str
    redis_channel: str
    pubsub: PubSub
    _task: asyncio.Task[None]
    _closed: bool = field(default=False, init=False)

    async def close(self) -> None:
        """Unsubscribe and stop the listener task; safe to call repeatedly."""
        if self._closed:
            return

        self._closed = True
        await self.pubsub.unsubscribe(self.redis_channel)
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        await self.pubsub.aclose()  # type: ignore[no-untyped-call]

    async def __aenter__(self) -> Self:
        """Return this handle when used as an async context manager."""
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Close the subscription when leaving an async context manager."""
        await self.close()


def redis_channel_name(channel: str) -> str:
    """Return the Redis channel key for a public realtime channel."""
    return f"{REDIS_CHANNEL_PREFIX}{channel}"


async def publish_to_channel(
    channel: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Publish a typed event envelope to a realtime channel.

    Redis pub/sub returns the number of active receivers. The caller does not
    need that value because no-subscriber publishes are expected and harmless.
    """
    event = {
        "type": "event",
        "channel": channel,
        "event_type": event_type,
        "payload": payload,
    }
    await get_redis().publish(redis_channel_name(channel), json.dumps(event))


async def subscribe_channel(
    channel: str,
    handler: RealtimeHandler,
) -> SubscriptionHandle:
    """Subscribe `handler` to every event published on a realtime channel."""
    pubsub = get_redis().pubsub(ignore_subscribe_messages=True)
    redis_channel = redis_channel_name(channel)
    await pubsub.subscribe(redis_channel)

    task = asyncio.create_task(
        _listen_for_events(channel=channel, pubsub=pubsub, handler=handler)
    )
    return SubscriptionHandle(
        channel=channel,
        redis_channel=redis_channel,
        pubsub=pubsub,
        _task=task,
    )


async def _listen_for_events(
    *,
    channel: str,
    pubsub: PubSub,
    handler: RealtimeHandler,
) -> None:
    """Read Redis pub/sub messages and dispatch decoded realtime events."""
    log = logger.bind(module="realtime", action="pubsub_listen", channel=channel)
    try:
        async for raw_message in pubsub.listen():
            message = _normalize_message(raw_message)
            if message is None:
                continue

            event = _decode_event(message["data"])
            if event is None:
                log.warning("malformed_pubsub_event")
                continue

            result = handler(event)
            if isawaitable(result):
                await result
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.error("pubsub_listener_failed", error=str(exc))
        raise


def _normalize_message(raw_message: object) -> dict[str, Any] | None:
    """Return message dictionaries for Redis pubsub data events only."""
    if not isinstance(raw_message, dict):
        return None
    if raw_message.get("type") != "message":
        return None
    return raw_message


def _decode_event(raw_data: object) -> RealtimeEvent | None:
    """Decode one JSON event envelope from Redis pub/sub data."""
    if isinstance(raw_data, bytes):
        raw_data = raw_data.decode("utf-8")
    if not isinstance(raw_data, str):
        return None

    try:
        decoded = json.loads(raw_data)
    except json.JSONDecodeError:
        return None

    if not isinstance(decoded, dict):
        return None
    return decoded
