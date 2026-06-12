"""Migration coverage for Phase 5c Slice 1 GDPR schema.

GDPR export, deletion, and consent flows are cross-cutting. This foundation
test keeps the durable tables, enum labels, and platform config seeds stable
before endpoint and worker slices build on them.
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
from app.modules.gdpr.models import (
    ACCOUNT_DELETION_STATUS_ENUM,
    CONSENT_DOCUMENT_ENUM,
    DATA_EXPORT_STATUS_ENUM,
    AccountDeletionRequest,
    ConsentLog,
    DataExportRequest,
)

PHASE_5B2_HEAD = "2026_06_11_0021"
GDPR_TABLES = {
    "account_deletion_requests",
    "consent_logs",
    "data_export_requests",
}
GDPR_CONFIG_DEFAULTS = {
    "account_deletion_grace_days": "14",
    "consent_version_privacy_policy": "1.0",
    "consent_version_terms_of_service": "1.0",
    "data_export_expiry_days": "7",
}


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Run Phase 5c Slice 1 migrations and restore the local DB afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.downgrade(alembic_config, PHASE_5B2_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PHASE_5B2_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_gdpr_migration_creates_tables_indexes_enums_and_config(
    migrated_engine: Engine,
) -> None:
    """Alembic creates GDPR tables, enum labels, indexes, and config defaults."""
    inspector = inspect(migrated_engine)
    table_names = set(inspector.get_table_names())
    export_indexes = {
        index["name"] for index in inspector.get_indexes("data_export_requests")
    }
    deletion_indexes = {
        index["name"]
        for index in inspector.get_indexes("account_deletion_requests")
    }
    consent_indexes = {index["name"] for index in inspector.get_indexes("consent_logs")}

    with migrated_engine.connect() as connection:
        enum_labels = {
            row[0]: set(row[1])
            for row in connection.execute(
                text(
                    """
                    SELECT
                        pg_type.typname,
                        array_agg(
                            pg_enum.enumlabel
                            ORDER BY pg_enum.enumsortorder
                        )
                    FROM pg_enum
                    JOIN pg_type ON pg_type.oid = pg_enum.enumtypid
                    WHERE pg_type.typname IN (
                        'account_deletion_status_enum',
                        'consent_document_enum',
                        'data_export_status_enum'
                    )
                    GROUP BY pg_type.typname
                    """
                )
            )
        }
        config_rows = {
            row[0]: row[1]
            for row in connection.execute(
                text(
                    """
                    SELECT key, value
                    FROM platform_config
                    WHERE key IN (
                        'account_deletion_grace_days',
                        'consent_version_privacy_policy',
                        'consent_version_terms_of_service',
                        'data_export_expiry_days'
                    )
                    """
                )
            )
        }

    assert GDPR_TABLES.issubset(table_names)
    assert "idx_data_export_requests_user_status" in export_indexes
    assert "uq_data_export_requests_one_active" in export_indexes
    assert "idx_account_deletion_requests_status_scheduled" in deletion_indexes
    assert "uq_account_deletion_requests_one_active" in deletion_indexes
    assert "idx_consent_logs_user_document_accepted" in consent_indexes
    assert enum_labels["data_export_status_enum"] == {
        "expired",
        "failed",
        "pending",
        "processing",
        "ready",
    }
    assert enum_labels["account_deletion_status_enum"] == {
        "blocked",
        "cancelled",
        "completed",
        "pending",
        "scheduled",
    }
    assert enum_labels["consent_document_enum"] == {
        "privacy_policy",
        "terms_of_service",
    }
    assert config_rows == GDPR_CONFIG_DEFAULTS


def test_gdpr_migration_downgrade_removes_slice_one_schema() -> None:
    """Downgrade removes GDPR tables and config seeds."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PHASE_5B2_HEAD)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())

        with engine.connect() as connection:
            config_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM platform_config
                    WHERE key IN (
                        'account_deletion_grace_days',
                        'consent_version_privacy_policy',
                        'consent_version_terms_of_service',
                        'data_export_expiry_days'
                    )
                    """
                )
            ).scalar_one()

        assert GDPR_TABLES.isdisjoint(table_names)
        assert config_count == 0
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_gdpr_orm_models_bind_to_slice_one_tables() -> None:
    """ORM metadata exposes GDPR schema for later endpoint and worker slices."""
    configure_mappers()

    assert DataExportRequest.__tablename__ == "data_export_requests"
    assert {"user_id", "status", "bundle_key", "expires_at"}.issubset(
        DataExportRequest.__table__.columns.keys()
    )
    assert AccountDeletionRequest.__tablename__ == "account_deletion_requests"
    assert {"user_id", "status", "blocked_reasons", "scheduled_for"}.issubset(
        AccountDeletionRequest.__table__.columns.keys()
    )
    assert ConsentLog.__tablename__ == "consent_logs"
    assert {"user_id", "document_type", "version", "accepted_at"}.issubset(
        ConsentLog.__table__.columns.keys()
    )
    assert set(DATA_EXPORT_STATUS_ENUM.enums) == {
        "expired",
        "failed",
        "pending",
        "processing",
        "ready",
    }
    assert set(ACCOUNT_DELETION_STATUS_ENUM.enums) == {
        "blocked",
        "cancelled",
        "completed",
        "pending",
        "scheduled",
    }
    assert set(CONSENT_DOCUMENT_ENUM.enums) == {
        "privacy_policy",
        "terms_of_service",
    }
