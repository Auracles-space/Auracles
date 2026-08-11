"""Migration coverage for the provider-neutral financial events ledger.

The ledger records one immutable row per money state change so a failed or
disputed payment can be reconstructed in order, across both payment providers.

Maps to: FR-FIN-* traceability, CLAUDE.md "Logging Standards" financial events.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from app.core.config import get_settings

PREVIOUS_HEAD = "2026_07_19_0091"
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


def test_financial_events_table_has_trace_columns(migrated_engine: Engine) -> None:
    """The ledger stores who/what/why for every money state change.

    `from_status`/`to_status` make a transition reconstructable, and the
    normalized `reason_code`/`reason_message` pair carries failure cause
    without binding the schema to one provider's error shape.
    """
    inspector = inspect(migrated_engine)

    assert "financial_events" in inspector.get_table_names()

    columns = {column["name"] for column in inspector.get_columns("financial_events")}
    assert {
        "id",
        "entity_type",
        "entity_id",
        "event_type",
        "from_status",
        "to_status",
        "amount",
        "currency",
        "provider",
        "provider_ref",
        "reason_code",
        "reason_message",
        "actor_id",
        "occurred_at",
        "metadata",
    }.issubset(columns)


def test_financial_events_indexes_support_entity_trace(migrated_engine: Engine) -> None:
    """Tracing one payment must be an indexed lookup, not a scan.

    The entity index is what `audit_logs` cannot offer: money events there are
    split across several `target_type` values, so per-payment history needs a
    dedicated entity-first index.
    """
    inspector = inspect(migrated_engine)
    index_names = {index["name"] for index in inspector.get_indexes("financial_events")}

    assert {
        "idx_financial_events_entity",
        "idx_financial_events_occurred_at",
        "idx_financial_events_event_type",
        "idx_financial_events_provider_ref",
    }.issubset(index_names)


def test_financial_events_constraints_guard_money_fields(
    migrated_engine: Engine,
) -> None:
    """Amount and currency travel together, and amounts are never negative."""
    inspector = inspect(migrated_engine)
    check_names = {
        check["name"] for check in inspector.get_check_constraints("financial_events")
    }

    assert {
        "ck_financial_events_amount_positive",
        "ck_financial_events_currency_with_amount",
        "ck_financial_events_entity_type",
    }.issubset(check_names)


def test_downgrade_removes_financial_events() -> None:
    """Downgrade -1 removes the ledger cleanly so the migration is reversible."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))

    command.downgrade(alembic_config, PREVIOUS_HEAD)
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PREVIOUS_HEAD)
    try:
        inspector = inspect(engine)
        assert "financial_events" not in inspector.get_table_names()
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
