"""Unit tests for the weekend-only business-day helper."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.shared.business_days import add_business_days


def test_friday_plus_one_is_monday() -> None:
    """One business day after a Friday lands on the following Monday."""
    friday = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)  # 2026-07-03 is a Friday
    assert add_business_days(friday, 1) == datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def test_five_business_days_skips_one_weekend() -> None:
    """Five business days from Monday lands on the next Monday."""
    monday = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)
    assert add_business_days(monday, 5) == datetime(2026, 7, 13, 9, 0, tzinfo=UTC)


def test_saturday_start_first_business_day_is_monday() -> None:
    """Counting from a weekend advances into Monday for the first day."""
    saturday = datetime(2026, 7, 4, 8, 0, tzinfo=UTC)  # Saturday
    assert add_business_days(saturday, 1) == datetime(2026, 7, 6, 8, 0, tzinfo=UTC)


def test_zero_business_days_returns_start_in_utc() -> None:
    """Zero business days returns the start moment normalized to UTC."""
    start = datetime(2026, 7, 6, 10, 30, tzinfo=UTC)
    assert add_business_days(start, 0) == start


def test_negative_raises() -> None:
    """A negative business-day count is rejected."""
    with pytest.raises(ValueError):
        add_business_days(datetime(2026, 7, 6, tzinfo=UTC), -1)
