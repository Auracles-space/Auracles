"""Unit tests for registration role-combination rules.

Operator and Contributor may coexist on one account, but Attestor is a
standalone role and cannot be combined with any other at registration.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.auth.schemas import RegisterRequest

_PASSWORD = "StrongerPass123!"


def _request(roles: list[str]) -> RegisterRequest:
    """Build a RegisterRequest with the given roles and valid other fields."""
    return RegisterRequest(
        email="role-rules@auracles.space",
        password=_PASSWORD,  # type: ignore[arg-type]
        display_name="Role Rules",
        roles=roles,  # type: ignore[arg-type]
    )


def test_operator_and_contributor_can_coexist() -> None:
    """A user may register as both Operator and Contributor."""
    request = _request(["operator", "contributor"])
    assert set(request.roles) == {"operator", "contributor"}


def test_attestor_alone_is_allowed() -> None:
    """Attestor on its own is a valid registration."""
    assert _request(["attestor"]).roles == ["attestor"]


def test_attestor_cannot_combine_with_operator() -> None:
    """Attestor combined with Operator is rejected."""
    with pytest.raises(ValidationError):
        _request(["attestor", "operator"])


def test_attestor_cannot_combine_with_contributor() -> None:
    """Attestor combined with Contributor is rejected."""
    with pytest.raises(ValidationError):
        _request(["attestor", "contributor"])


def test_attestor_cannot_combine_with_all_roles() -> None:
    """Attestor combined with Operator and Contributor is rejected."""
    with pytest.raises(ValidationError):
        _request(["attestor", "contributor", "operator"])
