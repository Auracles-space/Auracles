"""Unit tests for the ``require_step_up`` dependency.

Sensitive endpoints compose this dependency beside their role gate. It never
verifies a code itself: it only checks that the caller holds an open step-up
window (see the 2026-09-13 step-up design).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.dependencies import require_step_up
from app.modules.auth.models import User
from app.modules.auth.service import step_up_key

pytestmark = pytest.mark.asyncio


class _FakeRedis:
    """Minimal Redis double: string get/set/delete with recorded TTLs."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.values[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        return sum(self.values.pop(key, None) is not None for key in keys)


def _user(*, totp_enabled: bool) -> User:
    """Build an in-memory user without touching the database."""
    return User(
        id=uuid4(),
        email=f"{uuid4().hex[:8]}@auracles.space",
        password_hash="x",
        display_name="Step Up",
        email_verified=True,
        totp_enabled=totp_enabled,
    )


async def test_passes_when_window_is_open() -> None:
    """A user with 2FA and an open window is returned unchanged."""
    user = _user(totp_enabled=True)
    redis = _FakeRedis()
    await redis.set(step_up_key(user.id), datetime.now(UTC).isoformat(), ex=600)

    assert await require_step_up(user=user, redis=redis) is user


async def test_rejects_when_window_is_closed() -> None:
    """No window → 403 ``step_up_required`` so the client can prompt and retry."""
    user = _user(totp_enabled=True)

    with pytest.raises(HTTPException) as excinfo:
        await require_step_up(user=user, redis=_FakeRedis())

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail["error_code"] == "step_up_required"


async def test_rejects_when_two_factor_not_enrolled() -> None:
    """Without 2FA the user is sent to security settings, not to a code prompt."""
    user = _user(totp_enabled=False)

    with pytest.raises(HTTPException) as excinfo:
        await require_step_up(user=user, redis=_FakeRedis())

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail["error_code"] == "totp_setup_required"
    assert excinfo.value.detail["onboarding_url"] == "/settings/security"


async def test_if_enrolled_variant_skips_unenrolled_users() -> None:
    """Email change and account deletion must stay reachable without 2FA."""
    from app.core.dependencies import require_step_up_if_enrolled

    user = _user(totp_enabled=False)

    assert await require_step_up_if_enrolled(user=user, redis=_FakeRedis()) is user


async def test_if_enrolled_variant_gates_enrolled_users() -> None:
    """An enrolled user without an open window is still asked to step up."""
    from app.core.dependencies import require_step_up_if_enrolled

    user = _user(totp_enabled=True)

    with pytest.raises(HTTPException) as excinfo:
        await require_step_up_if_enrolled(user=user, redis=_FakeRedis())

    assert excinfo.value.detail["error_code"] == "step_up_required"
