"""Unit tests for the canonical shared taxonomy and its validators."""

from __future__ import annotations

import pytest

from app.shared import taxonomy


def test_functions_includes_investment_management() -> None:
    """investment_management is a first-class canonical function."""
    assert "investment_management" in taxonomy.FUNCTIONS


def test_sectors_are_canonical_slugs() -> None:
    """Sector set uses snake_case framework slugs instead of attestor labels."""
    assert "private_equity" in taxonomy.SECTORS
    assert "PE" not in taxonomy.SECTORS


def test_validate_functions_accepts_canonical_and_dedupes() -> None:
    """Known values pass; duplicates collapse first-seen; order is preserved."""
    assert taxonomy.validate_functions(
        ["compliance", "risk_management", "compliance"]
    ) == ["compliance", "risk_management"]


def test_validate_functions_rejects_unknown() -> None:
    """An off-vocabulary function raises ValueError."""
    with pytest.raises(ValueError, match="not a valid function"):
        taxonomy.validate_functions(["Compliance"])


def test_validate_sectors_requires_at_least_one() -> None:
    """An empty list is rejected."""
    with pytest.raises(ValueError, match="at least one sector"):
        taxonomy.validate_sectors([])


def test_validate_jurisdictions_accepts_slug() -> None:
    """Jurisdiction slugs validate against the canonical set."""
    assert taxonomy.validate_jurisdictions(["united_states", "nigeria"]) == [
        "united_states",
        "nigeria",
    ]
