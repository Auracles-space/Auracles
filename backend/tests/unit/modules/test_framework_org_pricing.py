"""Unit tests for per-organization Framework pricing.

Covers the additive org_price column, PricingConfig validation, the
resolve_license_price helper, and service persistence rules. Maps to
docs/superpowers/specs/2026-07-13-per-org-framework-pricing-design.md.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.main import app

BACKEND_DIR = Path(__file__).resolve().parents[3]


def _alembic_config() -> Config:
    """Build an Alembic config pointed at the backend migrations tree."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def test_migration_adds_org_price_column_and_downgrades() -> None:
    """org_price exists at head and the migration downgrades one step cleanly."""
    sync_engine = create_engine(app.state.settings.sync_database_url, pool_pre_ping=True)
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    columns = {column["name"] for column in inspect(sync_engine).get_columns("frameworks")}
    assert "org_price" in columns

    command.downgrade(cfg, "2026_07_11_0079")
    columns_after = {
        column["name"] for column in inspect(sync_engine).get_columns("frameworks")
    }
    assert "org_price" not in columns_after

    command.upgrade(cfg, "head")
    sync_engine.dispose()
