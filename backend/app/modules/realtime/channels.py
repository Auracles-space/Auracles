"""Realtime channel resolution and subscription authorization.

The WebSocket gateway will call this module before subscribing a socket to a
client-requested channel. User channels are self-only. Project channels delegate
membership to a callable so Slice 2 stays independent of the Projects service.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from inspect import isawaitable
from typing import Literal, cast
from uuid import UUID

type ChannelKind = Literal["user", "project"]
type ProjectMembershipChecker = Callable[
    [UUID, UUID],
    bool | Awaitable[bool],
]


class ChannelResolutionError(ValueError):
    """Raised when a client asks for a malformed realtime channel."""


@dataclass(frozen=True)
class ResolvedChannel:
    """Parsed channel name with its typed resource identifier."""

    kind: ChannelKind
    resource_id: UUID

    @property
    def name(self) -> str:
        """Return the canonical public channel name."""
        return f"{self.kind}:{self.resource_id}"


def resolve_channel(channel: str) -> ResolvedChannel:
    """Parse a public channel name into a typed channel descriptor."""
    raw_kind, separator, raw_resource_id = channel.partition(":")
    if separator != ":" or raw_kind not in {"user", "project"}:
        raise ChannelResolutionError("Unsupported realtime channel.")

    try:
        resource_id = UUID(raw_resource_id)
    except ValueError as exc:
        raise ChannelResolutionError("Realtime channel id must be a UUID.") from exc

    return ResolvedChannel(kind=cast(ChannelKind, raw_kind), resource_id=resource_id)


async def can_subscribe_to_channel(
    channel: str,
    user_id: UUID,
    *,
    project_membership_checker: ProjectMembershipChecker | None = None,
) -> bool:
    """Return whether `user_id` is allowed to subscribe to `channel`.

    Project membership is intentionally injected. Slice 9 can wire the real
    database-backed project member check without changing this public contract.
    """
    resolved = resolve_channel(channel)

    if resolved.kind == "user":
        return resolved.resource_id == user_id

    if project_membership_checker is None:
        return False

    result = project_membership_checker(resolved.resource_id, user_id)
    if isawaitable(result):
        result = await result
    return bool(result)
