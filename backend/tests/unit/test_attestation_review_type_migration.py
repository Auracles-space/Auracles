"""Migration coverage for Module 2a review-type, brief, fees, and SLA."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.core.config import get_settings

PRIOR_HEAD = "2026_06_29_0043"

# The 10-day-SLA config keys are seeded far below PRIOR_HEAD (migration 0013)
# and only ever UPDATEd by 0044 — never re-inserted. Sibling suites that run
# `delete(PlatformConfig)` can wipe them, leaving 0044's UPDATE a no-op. Re-seed
# the pre-0044 state ('7') so this migration test is independent of that
# ambient pollution.
_SLA_SEED_KEYS = (
    "attestation_completion_sla_days_framework",
    "attestation_completion_sla_days_contributor",
    "attestation_completion_sla_days_operator",
    "attestation_completion_sla_days_credential",
)


def _seed_sla_defaults(engine: Engine) -> None:
    """Ensure the completion-SLA config rows exist at their pre-0044 value."""
    with engine.begin() as connection:
        for key in _SLA_SEED_KEYS:
            connection.execute(
                text(
                    "INSERT INTO platform_config (key, value) VALUES (:key, '7') "
                    "ON CONFLICT (key) DO NOTHING"
                ).bindparams(key=key)
            )


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Upgrade to head and restore the local DB afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")
    command.downgrade(alembic_config, PRIOR_HEAD)
    _seed_sla_defaults(engine)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PRIOR_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_review_type_columns_enum_and_config(migrated_engine: Engine) -> None:
    """Upgrade adds review_type/brief, the enum, review fees, and SLA = 10."""
    inspector = inspect(migrated_engine)
    columns = {col["name"] for col in inspector.get_columns("attestations")}
    with migrated_engine.connect() as connection:
        enums = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT typname FROM pg_type "
                    "WHERE typname = 'attestation_review_type_enum'"
                )
            )
        }
        config_rows = connection.execute(text("SELECT key, value FROM platform_config"))
        config = {row.key: row.value for row in config_rows}

    assert {"review_type", "brief"}.issubset(columns)
    assert "attestation_review_type_enum" in enums
    assert config["attestation_fee_review_quality"] == "150000.00"
    assert config["attestation_fee_review_compliance"] == "350000.00"
    assert config["attestation_fee_review_expert"] == "750000.00"
    assert config["attestation_fee_review_provenance"] == "150000.00"
    assert config["attestation_completion_sla_days_framework"] == "10"
    assert config["attestation_completion_sla_days_credential"] == "10"


def test_downgrade_reverts_review_type_changes() -> None:
    """Downgrade drops the columns/enum, removes review fees, restores SLA = 7."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")
    command.downgrade(alembic_config, PRIOR_HEAD)
    _seed_sla_defaults(engine)
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PRIOR_HEAD)
    try:
        inspector = inspect(engine)
        columns = {col["name"] for col in inspector.get_columns("attestations")}
        with engine.connect() as connection:
            enums = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT typname FROM pg_type "
                        "WHERE typname = 'attestation_review_type_enum'"
                    )
                )
            }
            config_keys = {
                row[0]
                for row in connection.execute(text("SELECT key FROM platform_config"))
            }
            framework_sla = connection.execute(
                text(
                    "SELECT value FROM platform_config "
                    "WHERE key = 'attestation_completion_sla_days_framework'"
                )
            ).scalar_one_or_none()

        assert "review_type" not in columns
        assert "brief" not in columns
        assert "attestation_review_type_enum" not in enums
        assert "attestation_fee_review_quality" not in config_keys
        assert framework_sla == "7"
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
