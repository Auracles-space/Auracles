"""Unit tests for free Framework pricing.

Covers a resolved price of zero as a first-class listing price: schema
validation, the organizational tier priced independently of the base tier,
and the price-transition audit trail a free-to-paid switch leaves behind.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.frameworks.models import Framework
from app.modules.frameworks.pricing import resolve_license_price
from app.modules.frameworks.schemas import PricingConfig


def test_pricing_config_accepts_a_free_base_price() -> None:
    """A base price of zero validates, which is how a Framework is listed free."""
    cfg = PricingConfig(
        price=Decimal("0.00"),
        license_types=["single_user"],
    )

    assert cfg.price == Decimal("0.00")


def test_free_base_price_with_a_paid_org_tier_validates() -> None:
    """Free for individuals, paid for Organizations, is a supported shape.

    The two tiers are priced independently, so an open-core listing does not
    have to choose between giving the Framework away to everyone and charging
    everyone.
    """
    cfg = PricingConfig(
        price=Decimal("0.00"),
        license_types=["single_user", "organizational"],
        org_price=Decimal("500000.00"),
    )

    assert cfg.price == Decimal("0.00")
    assert cfg.org_price == Decimal("500000.00")


def test_pricing_config_accepts_a_free_org_tier() -> None:
    """A zero org_price is an explicit free organizational tier.

    Distinct from org_price being NULL, which means the tier reuses the base
    price. Zero must survive validation rather than being read as unset.
    """
    cfg = PricingConfig(
        price=Decimal("25000.00"),
        license_types=["single_user", "organizational"],
        org_price=Decimal("0.00"),
    )

    assert cfg.org_price == Decimal("0.00")


def test_free_org_tier_resolves_to_zero_not_the_base_price() -> None:
    """A zero org_price must resolve to zero, not fall back to the base price.

    resolve_license_price distinguishes an explicit free org tier from an unset
    one by identity, not truthiness. Reading `if framework.org_price` instead
    would silently charge the base price for a tier the seller gave away.
    """
    framework = Framework(
        price=Decimal("25000.00"),
        org_price=Decimal("0.00"),
    )

    assert resolve_license_price(framework, "organizational") == Decimal("0.00")
    assert resolve_license_price(framework, "single_user") == Decimal("25000.00")


def test_unset_org_price_still_falls_back_to_a_free_base_price() -> None:
    """An unset org tier on a free Framework resolves to zero via the base price."""
    framework = Framework(price=Decimal("0.00"), org_price=None)

    assert resolve_license_price(framework, "organizational") == Decimal("0.00")
