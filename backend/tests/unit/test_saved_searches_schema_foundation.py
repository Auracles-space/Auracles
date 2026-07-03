"""Migration coverage for Phase 5b-2 Slice 1 saved-search schema.

Saved searches drive alert delivery later in the phase, so the durable schema
must exist before CRUD, run parity, and Beat dispatch logic depend on it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import configure_mappers

from app.core.config import get_settings
from app.modules.frameworks.models import Framework
from app.modules.notifications.models import NOTIFICATION_TYPE_ENUM
from app.modules.saved_searches.models import (
    SavedSearch,
    SavedSearchAlertDelivery,
)

PHASE_5B1_HEAD = "2026_06_11_0020"
SAVED_SEARCH_TABLES = {"saved_searches", "saved_search_alert_deliveries"}


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Run Phase 5b-2 Slice 1 migrations and restore the local DB afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.downgrade(alembic_config, PHASE_5B1_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PHASE_5B1_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_saved_searches_migration_creates_tables_indexes_and_enum(
    migrated_engine: Engine,
) -> None:
    """Alembic creates the saved-search tables and alert notification label."""
    inspector = inspect(migrated_engine)
    table_names = set(inspector.get_table_names())
    saved_search_indexes = {
        index["name"] for index in inspector.get_indexes("saved_searches")
    }
    delivery_uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            "saved_search_alert_deliveries"
        )
    }
    framework_indexes = {index["name"] for index in inspector.get_indexes("frameworks")}

    with migrated_engine.connect() as connection:
        notification_labels = {
            row[0]
            for row in connection.execute(
                text(
                    """
                    SELECT enumlabel
                    FROM pg_enum
                    JOIN pg_type ON pg_type.oid = pg_enum.enumtypid
                    WHERE pg_type.typname = 'notification_type_enum'
                    """
                )
            )
        }
        config_value = connection.execute(
            text(
                """
                SELECT value
                FROM platform_config
                WHERE key = 'saved_search_alert_cadence_hours'
                """
            )
        ).scalar_one()

    assert SAVED_SEARCH_TABLES.issubset(table_names)
    assert "idx_saved_searches_user" in saved_search_indexes
    assert "idx_saved_searches_alerts" in saved_search_indexes
    assert "uq_saved_search_alert_deliveries_search_framework" in delivery_uniques
    assert "idx_frameworks_status_published_at" in framework_indexes
    assert "saved_search_alert" in notification_labels
    assert config_value == "24"


def test_saved_searches_migration_downgrade_removes_slice_one_schema() -> None:
    """Downgrade removes saved-search tables while preserving additive enum labels."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PHASE_5B1_HEAD)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        framework_indexes = {
            index["name"] for index in inspector.get_indexes("frameworks")
        }

        with engine.connect() as connection:
            config_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM platform_config
                    WHERE key = 'saved_search_alert_cadence_hours'
                    """
                )
            ).scalar_one()

        assert SAVED_SEARCH_TABLES.isdisjoint(table_names)
        assert "idx_frameworks_status_published_at" not in framework_indexes
        assert config_count == 0
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_saved_searches_orm_models_bind_to_slice_one_tables() -> None:
    """ORM metadata exposes stable saved-search tables for later slices."""
    configure_mappers()

    assert SavedSearch.__tablename__ == "saved_searches"
    assert {"user_id", "name", "filters", "alert_enabled"}.issubset(
        SavedSearch.__table__.columns.keys()
    )
    assert SavedSearchAlertDelivery.__tablename__ == ("saved_search_alert_deliveries")
    assert {"saved_search_id", "framework_id", "delivered_at"}.issubset(
        SavedSearchAlertDelivery.__table__.columns.keys()
    )
    assert "idx_frameworks_status_published_at" in {
        index.name for index in Framework.__table__.indexes
    }
    assert "saved_search_alert" in set(NOTIFICATION_TYPE_ENUM.enums)
