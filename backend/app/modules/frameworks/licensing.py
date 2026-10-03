"""Shared License grant rules.

Seat allocation is a property of the license tier, not of the rail that paid
for it, so every grant path reads it from here: the Stripe and Paystack
webhooks, Collection settlement, and the free-acquisition path, which writes
its License in-request because it has no provider callback to wait for.

This module imports nothing from the financials or webhooks packages so it can
be shared in both directions without a cycle.
"""

from __future__ import annotations


def license_seats_total(license_type: str) -> int | None:
    """Return the default seat allocation for a purchased license tier.

    Args:
        license_type: The license tier being granted.

    Returns:
        The seat count, or None for tiers that are not seat-limited.
    """
    if license_type == "single_user":
        return 1
    if license_type == "team":
        return 10
    return None
