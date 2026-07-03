"""Migration coverage for Organizations Core schema (migration 0058).

Verifies the org entity, membership (with single-owner partial unique
index), and capability status tables exist with their key constraints.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.core.config import get_settings

PREVIOUS_HEAD = "2026_07_02_0057"
BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Run migrations to head and restore the prior revision afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.downgrade(alembic_config, PREVIOUS_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PREVIOUS_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_organizations_tables_exist(migrated_engine: Engine) -> None:
    """Migration 0058 creates organizations, org_members, org_capabilities."""
    inspector = inspect(migrated_engine)
    tables = inspector.get_table_names()

    assert "organizations" in tables
    assert "org_members" in tables
    assert "org_capabilities" in tables


def test_org_members_single_owner_index(migrated_engine: Engine) -> None:
    """org_members carries the single-owner partial unique index."""
    with migrated_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE tablename = 'org_members' "
                "AND indexname = 'uq_org_members_single_owner'"
            )
        ).first()

    assert row is not None
    assert "WHERE" in row[0] and "owner" in row[0]


def test_organizations_slug_unique(migrated_engine: Engine) -> None:
    """organizations.slug is unique."""
    inspector = inspect(migrated_engine)
    uniques = inspector.get_unique_constraints("organizations") + [
        {"column_names": index["column_names"]}
        for index in inspector.get_indexes("organizations")
        if index.get("unique")
    ]

    assert any(unique["column_names"] == ["slug"] for unique in uniques)
