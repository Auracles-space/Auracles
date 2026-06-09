"""Unit tests for realtime channel resolution.

The WebSocket gateway arrives later, but Slice 2 defines the channel contract
that gateway code must use before subscribing a user to Redis-backed events.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.modules.realtime.channels import can_subscribe_to_channel


@pytest.mark.asyncio
async def test_user_channel_allows_only_the_matching_user() -> None:
    """A user channel is private to the matching authenticated user id."""
    user_id = uuid4()
    other_user_id = uuid4()

    assert await can_subscribe_to_channel(f"user:{user_id}", user_id)
    assert not await can_subscribe_to_channel(f"user:{user_id}", other_user_id)


@pytest.mark.asyncio
async def test_project_channel_uses_injected_membership_checker() -> None:
    """A project channel is authorized only through the membership hook."""
    project_id = uuid4()
    user_id = uuid4()
    seen: list[tuple[object, object]] = []

    async def checker(project: object, user: object) -> bool:
        """Record the requested membership check and allow this test user."""
        seen.append((project, user))
        return project == project_id and user == user_id

    assert not await can_subscribe_to_channel(f"project:{project_id}", user_id)
    assert await can_subscribe_to_channel(
        f"project:{project_id}",
        user_id,
        project_membership_checker=checker,
    )
    assert seen == [(project_id, user_id)]
