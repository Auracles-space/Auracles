"""Migration coverage for Phase 5d Slice 1 admin analytics schema foundation.

These tests lock the durable admin analytics snapshot table and the reversible
user-suspension columns before dashboard and moderation slices build on them.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import configure_mappers

from app.core.config import get_settings
from app.modules.admin.models import AnalyticsDailySnapshot
from app.modules.auth.models import User

PHASE_5C_HEAD = "2026_06_12_0022"


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Run Phase 5d Slice 1 migrations and restore the local DB afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.downgrade(alembic_config, PHASE_5C_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PHASE_5C_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_admin_migration_creates_snapshot_table_and_user_suspension_columns(
    migrated_engine: Engine,
) -> None:
    """Alembic creates the analytics snapshot table and suspension columns."""
    inspector = inspect(migrated_engine)
    table_names = set(inspector.get_table_names())
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    snapshot_indexes = {
        index["name"] for index in inspector.get_indexes("analytics_daily_snapshots")
    }

    assert "analytics_daily_snapshots" in table_names
    assert {
        "suspended_at",
        "suspended_by",
        "suspension_reason",
    }.issubset(user_columns)
    assert "idx_users_suspended_at_not_null" in {
        index["name"] for index in inspector.get_indexes("users")
    }
    assert "idx_analytics_daily_snapshots_computed_at" in snapshot_indexes


def test_admin_migration_downgrade_removes_slice_one_schema() -> None:
    """Downgrade removes the analytics snapshot table and suspension columns."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PHASE_5C_HEAD)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        user_columns = {column["name"] for column in inspector.get_columns("users")}

        assert "analytics_daily_snapshots" not in table_names
        assert {
            "suspended_at",
            "suspended_by",
            "suspension_reason",
        }.isdisjoint(user_columns)
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_admin_orm_models_bind_to_slice_one_tables() -> None:
    """ORM metadata exposes the admin snapshot table and user suspension fields."""
    configure_mappers()

    assert AnalyticsDailySnapshot.__tablename__ == "analytics_daily_snapshots"
    assert {
        "snapshot_date",
        "gmv_total",
        "gmv_by_source",
        "computed_at",
    }.issubset(AnalyticsDailySnapshot.__table__.columns.keys())
    assert {
        "suspended_at",
        "suspended_by",
        "suspension_reason",
    }.issubset(User.__table__.columns.keys())
