"""Weekend-only business-day arithmetic.

Provides the single helper used across the Attestation delivery/dispute flow
to compute business-day deadlines (dispute window, revision SLA, resolution
SLA). Weekends (Saturday/Sunday) are skipped; no holiday calendar is applied.
All arithmetic is anchored in UTC.

Maps to: Module 5 design spec section 4.1.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

SATURDAY = 5
SUNDAY = 6


def add_business_days(start: datetime, business_days: int) -> datetime:
    """Return the datetime ``business_days`` weekdays after ``start`` (UTC).

    Skips Saturday and Sunday. Preserves ``start``'s time-of-day. A count of
    zero returns ``start`` normalized to UTC.

    Args:
        start: The reference moment. Naive datetimes are treated as UTC.
        business_days: Non-negative number of weekdays to add.

    Returns:
        A timezone-aware UTC datetime.

    Raises:
        ValueError: If ``business_days`` is negative.
    """
    if business_days < 0:
        raise ValueError("business_days must be non-negative.")
    current = start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
    remaining = business_days
    while remaining > 0:
        current = current + timedelta(days=1)
        if current.weekday() not in (SATURDAY, SUNDAY):
            remaining -= 1
    return current
