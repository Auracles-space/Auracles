"""Migration coverage for notification preference schema foundation.

Phase 5 notification preferences start with durable per-user override storage
and enum types that later settings and worker slices depend on.
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
from app.modules.notifications.models import (
    NotificationDeliveryMarker,
    NotificationPreference,
)

PHASE_5E_HEAD = "2026_06_13_0025"


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Run the notification-preference migration and restore the local DB."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.downgrade(alembic_config, PHASE_5E_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PHASE_5E_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_notification_preferences_migration_creates_tables_indexes_and_enums(
    migrated_engine: Engine,
) -> None:
    """Alembic creates notification preference tables and supporting enums."""
    inspector = inspect(migrated_engine)
    table_names = set(inspector.get_table_names())
    preference_columns = {
        column["name"]
        for column in inspector.get_columns("notification_preferences")
    }
    marker_columns = {
        column["name"]
        for column in inspector.get_columns("notification_delivery_markers")
    }
    indexes = {
        index["name"]
        for index in inspector.get_indexes("notification_preferences")
    }
    uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            "notification_preferences"
        )
    }
    marker_uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            "notification_delivery_markers"
        )
    }

    with migrated_engine.connect() as connection:
        enum_rows = connection.execute(
            text(
                """
                SELECT pg_type.typname, pg_enum.enumlabel
                FROM pg_enum
                JOIN pg_type ON pg_type.oid = pg_enum.enumtypid
                WHERE pg_type.typname IN (
                    'notification_channel_enum',
                    'notification_category_enum'
                )
                ORDER BY pg_type.typname, pg_enum.enumsortorder
                """
            )
        )
        enum_labels: dict[str, list[str]] = {}
        for type_name, label in enum_rows:
            enum_labels.setdefault(type_name, []).append(label)

    assert "notification_preferences" in table_names
    assert "notification_delivery_markers" in table_names
    assert {
        "user_id",
        "notification_type",
        "category",
        "channel",
        "enabled",
    }.issubset(preference_columns)
    assert {"user_id", "dedupe_key", "channel"}.issubset(marker_columns)
    assert "idx_notification_preferences_user_type" in indexes
    assert "uq_notification_preferences_user_type_channel" in uniques
    assert (
        "uq_notification_delivery_markers_user_dedupe_channel" in marker_uniques
    )
    assert enum_labels["notification_channel_enum"] == ["email", "in_app"]
    assert enum_labels["notification_category_enum"] == [
        "project",
        "attestation",
        "financial",
        "discovery",
        "account",
    ]


def test_notification_preferences_migration_downgrade_removes_slice_one_schema(
) -> None:
    """Downgrade removes the preference table and its enum types."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PHASE_5E_HEAD)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        with engine.connect() as connection:
            enum_names = {
                row[0]
                for row in connection.execute(
                    text(
                        """
                        SELECT typname
                        FROM pg_type
                        WHERE typname IN (
                            'notification_channel_enum',
                            'notification_category_enum'
                        )
                        """
                    )
                )
            }

        assert "notification_preferences" not in table_names
        assert "notification_delivery_markers" not in table_names
        assert enum_names == set()
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_notification_preference_orm_model_binds_to_slice_one_table() -> None:
    """ORM metadata exposes the durable notification preference contract."""
    configure_mappers()

    assert NotificationPreference.__tablename__ == "notification_preferences"
    assert {
        "user_id",
        "notification_type",
        "category",
        "channel",
        "enabled",
    }.issubset(NotificationPreference.__table__.columns.keys())


def test_notification_delivery_marker_orm_model_binds_to_marker_table() -> None:
    """ORM metadata exposes the durable email-only delivery marker contract."""
    configure_mappers()

    assert NotificationDeliveryMarker.__tablename__ == "notification_delivery_markers"
    assert {"user_id", "dedupe_key", "channel"}.issubset(
        NotificationDeliveryMarker.__table__.columns.keys()
    )
