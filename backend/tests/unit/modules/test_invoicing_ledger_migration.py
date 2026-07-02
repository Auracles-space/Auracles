"""Migration coverage for the shared invoicing ledger (Module 6d)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from app.core.config import get_settings

PREVIOUS_HEAD = "2026_07_02_0055"
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


def test_invoicing_tables_and_constraints_exist(migrated_engine: Engine) -> None:
    """Upgrade creates the invoice ledger tables, uniques, and lookup index."""
    inspector = inspect(migrated_engine)

    assert "invoice_counters" in inspector.get_table_names()
    assert "invoices" in inspector.get_table_names()

    invoice_columns = {column["name"] for column in inspector.get_columns("invoices")}
    assert {
        "id",
        "series",
        "sequence_year",
        "sequence_number",
        "invoice_number",
        "doc_type",
        "issue_date",
        "currency",
        "subtotal",
        "tax_rate",
        "tax_amount",
        "total",
        "commission_rate",
        "net_amount",
        "seller_name",
        "seller_tax_id",
        "seller_address",
        "buyer_name",
        "buyer_email",
        "source_ref_type",
        "source_ref_id",
        "s3_key",
        "created_at",
    }.issubset(invoice_columns)

    unique_names = {c["name"] for c in inspector.get_unique_constraints("invoices")}
    assert {
        "uq_invoices_series_seq",
        "uq_invoices_number",
        "uq_invoices_source_doc",
    }.issubset(unique_names)

    index_names = {index["name"] for index in inspector.get_indexes("invoices")}
    assert "idx_invoices_source" in index_names


def test_downgrade_removes_invoicing_tables() -> None:
    """Downgrade -1 removes the new invoicing schema cleanly."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))

    command.downgrade(alembic_config, PREVIOUS_HEAD)
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PREVIOUS_HEAD)
    try:
        inspector = inspect(engine)
        assert "invoice_counters" not in inspector.get_table_names()
        assert "invoices" not in inspector.get_table_names()
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
