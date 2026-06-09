"""Integration tests for realtime Redis pub/sub primitives."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.core.redis import close_redis, get_redis
from app.modules.realtime.pubsub import publish_to_channel, subscribe_channel


@pytest.fixture(autouse=True)
async def redis_connection() -> None:
    """Skip realtime integration tests when local Redis is unavailable."""
    client = get_redis()
    try:
        await client.ping()
    except Exception as exc:
        await close_redis()
        pytest.skip(f"Redis unavailable for realtime integration test: {exc}")


@pytest.mark.asyncio
async def test_publish_to_channel_delivers_event_to_subscriber() -> None:
    """A published realtime event reaches a subscribed async handler."""
    channel = f"project:{uuid4()}"
    received: list[dict[str, object]] = []
    delivered = asyncio.Event()

    async def handler(event: dict[str, object]) -> None:
        """Record the event delivered by the pub/sub listener."""
        received.append(event)
        delivered.set()

    subscription = await subscribe_channel(channel, handler)
    payload = {"milestone_id": str(uuid4())}
    try:
        await publish_to_channel(channel, "milestone_funded", payload)
        await asyncio.wait_for(delivered.wait(), timeout=2)
    finally:
        await subscription.close()
        await close_redis()

    assert received == [
        {
            "type": "event",
            "channel": channel,
            "event_type": "milestone_funded",
            "payload": payload,
        }
    ]


@pytest.mark.asyncio
async def test_publish_without_subscribers_is_safe() -> None:
    """Publishing to an empty Redis channel is expected and harmless."""
    await publish_to_channel(
        f"user:{uuid4()}",
        "proposal_accepted",
        {"project_id": str(uuid4())},
    )
    await close_redis()
