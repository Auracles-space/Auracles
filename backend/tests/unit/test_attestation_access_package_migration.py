"""Migration coverage for Module 2b access-package schema."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.core.config import get_settings

PRIOR_HEAD = "2026_06_30_0044"


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Upgrade to head and restore the local DB afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")
    command.downgrade(alembic_config, PRIOR_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PRIOR_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_access_package_schema_added(migrated_engine: Engine) -> None:
    """Upgrade adds ack columns, the access table, enum value, and consent config."""
    inspector = inspect(migrated_engine)
    attestation_cols = {
        column["name"] for column in inspector.get_columns("attestations")
    }
    tables = set(inspector.get_table_names())
    with migrated_engine.connect() as connection:
        enum_values = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT e.enumlabel FROM pg_enum e "
                    "JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'attestation_status_enum'"
                )
            )
        }
        consent_cfg = connection.execute(
            text(
                "SELECT value FROM platform_config "
                "WHERE key = 'attestation_owner_consent_hours'"
            )
        ).scalar_one_or_none()

    assert {"content_ack_at", "content_ack_version"}.issubset(attestation_cols)
    assert "attestation_artifact_access" in tables
    assert "pending_owner_consent" in enum_values
    assert consent_cfg == "72"


def test_downgrade_reverts_access_package() -> None:
    """Downgrade drops ack columns, the access table, and the consent config."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")
    command.downgrade(alembic_config, PRIOR_HEAD)
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PRIOR_HEAD)
    try:
        inspector = inspect(engine)
        attestation_cols = {
            column["name"] for column in inspector.get_columns("attestations")
        }
        tables = set(inspector.get_table_names())
        with engine.connect() as connection:
            consent_cfg = connection.execute(
                text(
                    "SELECT value FROM platform_config "
                    "WHERE key = 'attestation_owner_consent_hours'"
                )
            ).scalar_one_or_none()
        assert "content_ack_at" not in attestation_cols
        assert "content_ack_version" not in attestation_cols
        assert "attestation_artifact_access" not in tables
        assert consent_cfg is None
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
