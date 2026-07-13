"""Framework license price resolution.

Single source of truth for the charge amount of a license tier, shared by the
individual and organization purchase paths so commission, payout split, and
transaction amount all inherit the correct value.

Maps to docs/superpowers/specs/2026-07-13-per-org-framework-pricing-design.md §5.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.frameworks.models import Framework


def resolve_license_price(framework: Framework, license_type: str) -> Decimal:
    """Return the charge amount for one license tier.

    The organizational tier falls back to the base price when `org_price` is
    NULL (the seller chose to reuse the single-user price). Every other tier
    charges the base price.

    Args:
        framework: The Framework being purchased.
        license_type: The requested license tier.

    Returns:
        The price to charge, as a Decimal.
    """
    if license_type == "organizational" and framework.org_price is not None:
        return framework.org_price
    return framework.price
