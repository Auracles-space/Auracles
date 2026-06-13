"""Unit tests for notification preference mapping and gate behavior.

Phase 5 notification preferences start by locking the event-type mapping and
the delivery gate semantics before the settings API and worker wiring build on
them.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.modules.notifications import preferences
from app.modules.notifications.models import NOTIFICATION_TYPE_ENUM


class _MissingRowSession:
    """Async-session double that simulates an absent preference row."""

    async def scalar(self, _statement: object) -> bool | None:
        """Return no matching row so the gate exercises the default path."""
        return None


class _ExplodingSession:
    """Async-session double that fails if code performs a DB lookup."""

    async def scalar(self, _statement: object) -> bool | None:
        """Raise immediately to prove critical notifications bypass storage."""
        raise AssertionError("critical notification lookup should bypass DB")


def test_every_notification_type_maps_to_a_display_category() -> None:
    """Every stored product notification type must have a category mapping."""
    notification_types = set(NOTIFICATION_TYPE_ENUM.enums)
    mapped_types = set(preferences.NOTIFICATION_TYPE_CATEGORY)

    assert mapped_types == notification_types


@pytest.mark.asyncio
async def test_should_deliver_defaults_to_enabled_when_no_row_exists() -> None:
    """Missing preference rows are opt-out and therefore still deliver."""
    allowed = await preferences.should_deliver(
        _MissingRowSession(),
        user_id=uuid4(),
        notification_type="proposal_accepted",
        channel="email",
    )

    assert allowed is True


@pytest.mark.asyncio
async def test_should_deliver_bypasses_preferences_for_critical_types() -> None:
    """Critical notification types always deliver and never consult storage."""
    allowed = await preferences.should_deliver(
        _ExplodingSession(),
        user_id=uuid4(),
        notification_type="dispute_resolved_release",
        channel="in_app",
    )

    assert allowed is True
