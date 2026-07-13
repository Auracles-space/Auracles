"""Unit tests for per-organization Framework pricing.

Covers the additive org_price column, PricingConfig validation, the
resolve_license_price helper, and service persistence rules. Maps to
docs/superpowers/specs/2026-07-13-per-org-framework-pricing-design.md.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect

from app.main import app
from app.modules.frameworks.models import Framework
from app.modules.frameworks.pricing import resolve_license_price
from app.modules.frameworks.schemas import PricingConfig
from app.modules.frameworks.service import _apply_framework_pricing_update

BACKEND_DIR = Path(__file__).resolve().parents[3]


def _alembic_config() -> Config:
    """Build an Alembic config pointed at the backend migrations tree."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def test_migration_adds_org_price_column_and_downgrades() -> None:
    """org_price exists at head and the migration downgrades one step cleanly."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    columns = {
        column["name"] for column in inspect(sync_engine).get_columns("frameworks")
    }
    assert "org_price" in columns

    command.downgrade(cfg, "2026_07_11_0079")
    columns_after = {
        column["name"] for column in inspect(sync_engine).get_columns("frameworks")
    }
    assert "org_price" not in columns_after

    command.upgrade(cfg, "head")
    sync_engine.dispose()


def test_pricing_config_accepts_org_tier_with_price() -> None:
    """Org tier plus an explicit org_price validates."""
    cfg = PricingConfig(
        price=Decimal("250.00"),
        license_types=["single_user", "organizational"],
        org_price=Decimal("900.00"),
    )
    assert cfg.org_price == Decimal("900.00")


def test_pricing_config_org_tier_without_price_means_reuse() -> None:
    """Org tier with org_price omitted is valid and left as None (reuse base)."""
    cfg = PricingConfig(
        price=Decimal("250.00"),
        license_types=["single_user", "organizational"],
    )
    assert cfg.org_price is None


def test_pricing_config_rejects_orphan_org_price() -> None:
    """org_price without the organizational tier is a 422-worthy error."""
    with pytest.raises(ValidationError):
        PricingConfig(
            price=Decimal("250.00"),
            license_types=["single_user"],
            org_price=Decimal("900.00"),
        )


def test_pricing_config_requires_single_user_tier() -> None:
    """single_user is mandatory on every framework."""
    with pytest.raises(ValidationError):
        PricingConfig(
            price=Decimal("250.00"),
            license_types=["organizational"],
            org_price=Decimal("900.00"),
        )


def test_pricing_config_allows_org_price_below_base() -> None:
    """A seller may price the org tier below the single-user price."""
    cfg = PricingConfig(
        price=Decimal("250.00"),
        license_types=["single_user", "organizational"],
        org_price=Decimal("100.00"),
    )
    assert cfg.org_price == Decimal("100.00")


def _framework(**kwargs: object) -> Framework:
    """Build an in-memory Framework with pricing defaults for unit assertions."""
    defaults: dict[str, object] = {
        "price": Decimal("250.00"),
        "currency": "USD",
        "license_types": ["single_user"],
        "org_price": None,
        "commercial_rights": None,
        "usage_restrictions": None,
    }
    defaults.update(kwargs)
    return Framework(**defaults)


def test_apply_pricing_sets_org_price() -> None:
    """Applying pricing with the org tier persists org_price."""
    framework = _framework()
    _apply_framework_pricing_update(
        framework,
        PricingConfig(
            price=Decimal("250.00"),
            license_types=["single_user", "organizational"],
            org_price=Decimal("900.00"),
        ),
    )
    assert framework.org_price == Decimal("900.00")
    assert framework.license_types == ["single_user", "organizational"]


def test_apply_pricing_nulls_org_price_when_tier_removed() -> None:
    """Removing the org tier on edit nulls org_price to keep the orphan invariant."""
    framework = _framework(
        license_types=["single_user", "organizational"],
        org_price=Decimal("900.00"),
    )
    _apply_framework_pricing_update(
        framework,
        PricingConfig(price=Decimal("250.00"), license_types=["single_user"]),
    )
    assert framework.org_price is None
    assert framework.license_types == ["single_user"]


def test_resolve_price_single_user_uses_base() -> None:
    """single_user always charges the base price."""
    framework = _framework(org_price=Decimal("900.00"))
    assert resolve_license_price(framework, "single_user") == Decimal("250.00")


def test_resolve_price_org_uses_org_price_when_set() -> None:
    """organizational charges org_price when it is set."""
    framework = _framework(
        license_types=["single_user", "organizational"],
        org_price=Decimal("900.00"),
    )
    assert resolve_license_price(framework, "organizational") == Decimal("900.00")


def test_resolve_price_org_falls_back_to_base_on_reuse() -> None:
    """organizational with a NULL org_price reuses the base price."""
    framework = _framework(
        license_types=["single_user", "organizational"],
        org_price=None,
    )
    assert resolve_license_price(framework, "organizational") == Decimal("250.00")
