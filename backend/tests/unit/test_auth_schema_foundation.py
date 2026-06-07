"""Tests for the Phase 1 auth schema foundation.

These tests exercise the public database contract introduced by Slice 1:
Alembic must be able to create the auth tables, and the ORM model classes
must expose stable table metadata for later auth slices.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.modules.auth.models import OAuthAccount, User, UserRole
from app.shared.models.audit_log import AuditLog


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Run Alembic to head for schema assertions and leave the DB at head."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        # Exercise rollback on every migration test, then restore the dev DB.
        command.downgrade(alembic_config, "-1")
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_auth_foundation_migration_creates_required_tables(
    migrated_engine: Engine,
) -> None:
    """Alembic creates the auth, OAuth, and audit tables required by Phase 1."""
    inspector = inspect(migrated_engine)

    assert {
        "users",
        "user_roles",
        "oauth_accounts",
        "audit_logs",
    }.issubset(set(inspector.get_table_names()))


def test_auth_foundation_migration_creates_enums_and_indexes(
    migrated_engine: Engine,
) -> None:
    """Alembic creates role/KYC enums and query indexes for the audit trail."""
    inspector = inspect(migrated_engine)
    audit_index_names = {
        index["name"] for index in inspector.get_indexes("audit_logs")
    }

    with migrated_engine.connect() as connection:
        enum_names = {
            row[0]
            for row in connection.execute(
                text("SELECT typname FROM pg_type WHERE typname LIKE '%_enum'")
            )
        }

    assert {"role_enum", "kyc_status_enum"}.issubset(enum_names)
    assert {
        "ix_audit_logs_actor_id_created_at",
        "ix_audit_logs_action_created_at",
    }.issubset(audit_index_names)


def test_auth_foundation_migration_downgrade_removes_slice_one_schema() -> None:
    """Alembic downgrade removes Slice 1 tables and enum types cleanly."""
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

        assert {
            "users",
            "user_roles",
            "oauth_accounts",
            "audit_logs",
        }.isdisjoint(table_names)
        assert {"role_enum", "kyc_status_enum"}.isdisjoint(enum_names)
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_auth_models_expose_phase_one_tables() -> None:
    """ORM models bind to the table names that later slices will query."""
    assert User.__tablename__ == "users"
    assert UserRole.__tablename__ == "user_roles"
    assert OAuthAccount.__tablename__ == "oauth_accounts"
    assert AuditLog.__tablename__ == "audit_logs"
