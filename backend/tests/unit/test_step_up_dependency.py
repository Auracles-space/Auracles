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
    assert excinfo.value.detail["onboarding_url"] == "/2fa-setup"


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


async def test_after_variant_runs_the_gate_before_the_window_check() -> None:
    """A caller who fails the role gate is refused by the gate, not asked to step up."""
    from app.core.dependencies import require_step_up_after

    async def gate() -> User:
        raise HTTPException(status_code=403, detail={"error_code": "role_required"})

    checker = require_step_up_after(gate)
    user = _user(totp_enabled=True)

    with pytest.raises(HTTPException) as excinfo:
        await checker(subject=await _raise_or_user(gate, user), redis=_FakeRedis())

    assert excinfo.value.detail["error_code"] == "role_required"


async def _raise_or_user(gate, user: User) -> User:  # type: ignore[no-untyped-def]
    """Resolve the gate the way FastAPI would, surfacing its HTTPException."""
    try:
        return await gate()
    except HTTPException:
        raise


async def test_after_variant_requires_a_window_once_the_gate_passes() -> None:
    """With the gate satisfied, the composed dependency still needs an open window."""
    from app.core.dependencies import require_step_up_after

    user = _user(totp_enabled=True)

    async def gate() -> User:
        return user

    checker = require_step_up_after(gate)

    with pytest.raises(HTTPException) as excinfo:
        await checker(subject=await gate(), redis=_FakeRedis())
    assert excinfo.value.detail["error_code"] == "step_up_required"

    redis = _FakeRedis()
    await redis.set(step_up_key(user.id), datetime.now(UTC).isoformat(), ex=600)
    assert await checker(subject=await gate(), redis=redis) is user


async def test_after_variant_accepts_an_organization_context() -> None:
    """Organization-role gates return a context carrying ``.user``; that works too."""
    from types import SimpleNamespace

    from app.core.dependencies import require_step_up_after

    user = _user(totp_enabled=True)
    context = SimpleNamespace(org=None, member=None, user=user)

    async def gate() -> object:
        return context

    checker = require_step_up_after(gate)
    redis = _FakeRedis()
    await redis.set(step_up_key(user.id), datetime.now(UTC).isoformat(), ex=600)

    assert await checker(subject=await gate(), redis=redis) is user
