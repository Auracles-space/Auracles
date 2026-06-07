"""Migration tests for the Phase 2 marketplace schema foundation.

Slice 1 is intentionally schema-only: it proves that Alembic can create and
remove the marketplace tables, enums, and indexes before any marketplace
service or router code starts depending on them.
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
from app.modules.frameworks.models import Framework, FrameworkVersion, License, Review
from app.modules.frameworks.models_artifact import (
    Artifact,
    ArtifactDownload,
    ArtifactPiiAudit,
    ArtifactRarityAudit,
)

MARKETPLACE_TABLES = {
    "frameworks",
    "framework_versions",
    "artifacts",
    "artifact_pii_audit",
    "artifact_rarity_audit",
    "licenses",
    "artifact_downloads",
    "reviews",
}
MARKETPLACE_ENUMS = {
    "framework_status_enum",
    "scan_status_enum",
    "processing_status_enum",
    "org_size_enum",
    "license_type_enum",
    "license_status_enum",
    "change_type_enum",
    "version_action_enum",
}


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Run marketplace migrations and leave the local database restored."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        # Exercise the Slice 1 rollback and then restore the developer DB.
        command.downgrade(alembic_config, "-1")
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_marketplace_migration_creates_tables_and_enums(
    migrated_engine: Engine,
) -> None:
    """Alembic creates the Phase 2 marketplace tables and DB enum types."""
    inspector = inspect(migrated_engine)

    with migrated_engine.connect() as connection:
        enum_names = {
            row[0]
            for row in connection.execute(
                text("SELECT typname FROM pg_type WHERE typname LIKE '%_enum'")
            )
        }

    assert MARKETPLACE_TABLES.issubset(set(inspector.get_table_names()))
    assert MARKETPLACE_ENUMS.issubset(enum_names)


def test_marketplace_migration_creates_query_indexes(
    migrated_engine: Engine,
) -> None:
    """Alembic creates the indexes needed for catalog and artifact queries."""
    inspector = inspect(migrated_engine)
    framework_indexes = {
        index["name"] for index in inspector.get_indexes("frameworks")
    }
    artifact_indexes = {
        index["name"] for index in inspector.get_indexes("artifacts")
    }
    download_indexes = {
        index["name"] for index in inspector.get_indexes("artifact_downloads")
    }

    assert {
        "idx_frameworks_status",
        "idx_frameworks_contributor",
        "idx_frameworks_category",
        "idx_frameworks_sector",
        "idx_frameworks_price",
        "idx_frameworks_search",
        "idx_frameworks_tags",
    }.issubset(framework_indexes)
    assert {
        "idx_artifacts_framework",
        "idx_artifacts_processing_status",
        "idx_artifacts_simhash",
    }.issubset(artifact_indexes)
    assert "idx_artifact_downloads_license" in download_indexes


def test_marketplace_migration_omits_pgvector(
    migrated_engine: Engine,
) -> None:
    """The marketplace schema follows the approved no-pgvector deviation."""
    with migrated_engine.connect() as connection:
        installed_extensions = {
            row[0]
            for row in connection.execute(text("SELECT extname FROM pg_extension"))
        }
        vector_columns = list(
            connection.execute(
                text(
                    """
                    SELECT table_name, column_name
                    FROM information_schema.columns
                    WHERE udt_name = 'vector'
                    """
                )
            )
        )

    assert "vector" not in installed_extensions
    assert vector_columns == []


def test_marketplace_migration_downgrade_removes_slice_one_schema() -> None:
    """Alembic downgrade removes marketplace tables and enum types cleanly."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "-1")
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())

        with engine.connect() as connection:
            enum_names = {
                row[0]
                for row in connection.execute(
                    text("SELECT typname FROM pg_type WHERE typname LIKE '%_enum'")
                )
            }

        assert MARKETPLACE_TABLES.isdisjoint(table_names)
        assert MARKETPLACE_ENUMS.isdisjoint(enum_names)
        assert {
            "users",
            "user_roles",
            "audit_logs",
            "kyc_documents",
        }.issubset(table_names)
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_marketplace_orm_models_bind_to_phase_two_tables() -> None:
    """Marketplace ORM models expose stable table metadata and relationships."""
    configure_mappers()

    assert Framework.__tablename__ == "frameworks"
    assert FrameworkVersion.__tablename__ == "framework_versions"
    assert Artifact.__tablename__ == "artifacts"
    assert ArtifactPiiAudit.__tablename__ == "artifact_pii_audit"
    assert ArtifactRarityAudit.__tablename__ == "artifact_rarity_audit"
    assert License.__tablename__ == "licenses"
    assert ArtifactDownload.__tablename__ == "artifact_downloads"
    assert Review.__tablename__ == "reviews"
