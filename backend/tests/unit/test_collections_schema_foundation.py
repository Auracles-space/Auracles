"""Migration coverage for Phase 5b-1 Slice 1 collection schema foundation.

Collections are a bundle purchase money path, so the database contract needs to
exist before CRUD, checkout, webhook minting, and refund logic can depend on it.
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
from app.modules.collections.models import (
    CollectionEarningAllocation,
    CollectionFramework,
    CollectionPurchaseSnapshot,
    FrameworkCollection,
)
from app.modules.frameworks.models import License

PHASE_5A_HEAD = "2026_06_11_0019"

COLLECTION_TABLES = {
    "framework_collections",
    "collection_frameworks",
    "collection_purchase_snapshots",
    "collection_earning_allocations",
}
COLLECTION_ENUMS = {
    "collection_status_enum",
    "license_source_enum",
}


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Run Phase 5b-1 Slice 1 migrations and restore the local DB afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.downgrade(alembic_config, PHASE_5A_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PHASE_5A_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_collections_migration_creates_tables_enums_and_license_extension(
    migrated_engine: Engine,
) -> None:
    """Alembic creates the Phase 5b-1 Slice 1 collection schema contract."""
    inspector = inspect(migrated_engine)
    license_columns = {column["name"] for column in inspector.get_columns("licenses")}
    collection_framework_pk = inspector.get_pk_constraint("collection_frameworks")
    snapshot_uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            "collection_purchase_snapshots"
        )
    }
    allocation_indexes = {
        index["name"]
        for index in inspector.get_indexes("collection_earning_allocations")
    }

    with migrated_engine.connect() as connection:
        enum_names = {
            row[0]
            for row in connection.execute(
                text("SELECT typname FROM pg_type WHERE typname LIKE '%_enum'")
            )
        }
        license_source_labels = {
            row[0]
            for row in connection.execute(
                text(
                    """
                    SELECT enumlabel
                    FROM pg_enum
                    JOIN pg_type ON pg_type.oid = pg_enum.enumtypid
                    WHERE pg_type.typname = 'license_source_enum'
                    """
                )
            )
        }

    assert COLLECTION_TABLES.issubset(set(inspector.get_table_names()))
    assert COLLECTION_ENUMS.issubset(enum_names)
    assert license_source_labels == {"individual", "collection"}
    assert {"source", "collection_id"}.issubset(license_columns)
    assert collection_framework_pk["constrained_columns"] == [
        "collection_id",
        "framework_id",
    ]
    assert "uq_collection_purchase_snapshots_transaction_framework" in snapshot_uniques
    assert "idx_collection_earning_allocations_transaction" in allocation_indexes


def test_collections_migration_downgrade_removes_slice_one_schema() -> None:
    """Downgrade removes collection tables, enums, and license extensions cleanly."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PHASE_5A_HEAD)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        license_columns = {
            column["name"] for column in inspector.get_columns("licenses")
        }

        with engine.connect() as connection:
            enum_names = {
                row[0]
                for row in connection.execute(
                    text("SELECT typname FROM pg_type WHERE typname LIKE '%_enum'")
                )
            }

        assert COLLECTION_TABLES.isdisjoint(table_names)
        assert COLLECTION_ENUMS.isdisjoint(enum_names)
        assert {"source", "collection_id"}.isdisjoint(license_columns)
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_collections_orm_models_bind_to_slice_one_tables() -> None:
    """ORM models expose stable metadata for later collection service slices."""
    configure_mappers()

    assert FrameworkCollection.__tablename__ == "framework_collections"
    assert {"title", "description", "bundle_price", "status"}.issubset(
        FrameworkCollection.__table__.columns.keys()
    )
    assert CollectionFramework.__tablename__ == "collection_frameworks"
    assert {"collection_id", "framework_id"}.issubset(
        CollectionFramework.__table__.columns.keys()
    )
    assert CollectionPurchaseSnapshot.__tablename__ == "collection_purchase_snapshots"
    assert {"transaction_id", "already_owned", "list_price_at_purchase"}.issubset(
        CollectionPurchaseSnapshot.__table__.columns.keys()
    )
    assert CollectionEarningAllocation.__tablename__ == (
        "collection_earning_allocations"
    )
    assert {"allocated_amount", "framework_id", "transaction_id"}.issubset(
        CollectionEarningAllocation.__table__.columns.keys()
    )
    assert {"source", "collection_id"}.issubset(License.__table__.columns.keys())
