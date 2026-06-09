"""Migration coverage for Phase 3 Slice 1 financial schema foundation.

These tests keep the first financials slice honest: Alembic must create the
durable payment, payout, escrow, webhook, and platform configuration schema
before any service endpoints are allowed to depend on it.
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
from app.modules.auth.models import User
from app.modules.financials.models import (
    Escrow,
    Payout,
    PayoutAccount,
    PlatformConfig,
    Transaction,
)
from app.modules.frameworks.models import License
from app.modules.webhooks.models import WebhookEvent

PHASE_TWO_HEAD = "2026_06_08_0008"

FINANCIAL_TABLES = {
    "transactions",
    "escrows",
    "payout_accounts",
    "payouts",
    "webhook_events",
    "platform_config",
}
FINANCIAL_ENUMS = {
    "transaction_type_enum",
    "transaction_status_enum",
    "payment_provider_enum",
    "escrow_status_enum",
    "payout_status_enum",
    "webhook_event_status_enum",
}
PLATFORM_CONFIG_SEEDS = {
    "commission_rate": "0.15",
    "min_payout_usd": "50",
    "min_payout_ngn": "20000",
    "refund_window_hours": "48",
}


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Run Phase 3 migrations and restore the local database afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.downgrade(alembic_config, PHASE_TWO_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PHASE_TWO_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_financials_migration_creates_tables_enums_and_seed_config(
    migrated_engine: Engine,
) -> None:
    """Alembic creates the Phase 3 Slice 1 schema and config defaults."""
    inspector = inspect(migrated_engine)

    with migrated_engine.connect() as connection:
        enum_names = {
            row[0]
            for row in connection.execute(
                text("SELECT typname FROM pg_type WHERE typname LIKE '%_enum'")
            )
        }
        license_type_labels = {
            row[0]
            for row in connection.execute(
                text(
                    """
                    SELECT enumlabel
                    FROM pg_enum
                    JOIN pg_type ON pg_type.oid = pg_enum.enumtypid
                    WHERE pg_type.typname = 'license_type_enum'
                    """
                )
            )
        }
        config_rows = {
            row.key: row.value
            for row in connection.execute(
                text("SELECT key, value FROM platform_config")
            )
        }

    assert FINANCIAL_TABLES.issubset(set(inspector.get_table_names()))
    assert FINANCIAL_ENUMS.issubset(enum_names)
    assert "organizational" in license_type_labels
    assert "white_label" not in license_type_labels
    assert PLATFORM_CONFIG_SEEDS.items() <= config_rows.items()


def test_financials_migration_links_existing_license_and_user_tables(
    migrated_engine: Engine,
) -> None:
    """Financials extends Phase 1/2 tables without recreating them."""
    inspector = inspect(migrated_engine)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    user_indexes = {index["name"] for index in inspector.get_indexes("users")}
    license_foreign_keys = {
        foreign_key["name"]: foreign_key
        for foreign_key in inspector.get_foreign_keys("licenses")
    }

    assert "stripe_customer_id" in user_columns
    assert "idx_users_stripe_customer_id" in user_indexes
    assert "fk_licenses_transaction_id_transactions" in license_foreign_keys
    assert license_foreign_keys["fk_licenses_transaction_id_transactions"][
        "referred_table"
    ] == "transactions"


def test_financials_migration_downgrade_restores_phase_two_license_enum() -> None:
    """Downgrade removes the additive license enum value while no data exists."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PHASE_TWO_HEAD)
    try:
        with engine.connect() as connection:
            license_type_labels = {
                row[0]
                for row in connection.execute(
                    text(
                        """
                        SELECT enumlabel
                        FROM pg_enum
                        JOIN pg_type ON pg_type.oid = pg_enum.enumtypid
                        WHERE pg_type.typname = 'license_type_enum'
                        """
                    )
                )
            }

        assert license_type_labels == {"single_user", "team", "enterprise"}
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_financials_orm_models_bind_to_slice_one_tables() -> None:
    """Financial ORM models expose stable table metadata for service slices."""
    configure_mappers()

    assert Transaction.__tablename__ == "transactions"
    assert {"payer_id", "payee_id", "provider_ref"}.issubset(
        Transaction.__table__.columns.keys()
    )
    assert Escrow.__tablename__ == "escrows"
    assert "release_conditions" in Escrow.__table__.columns.keys()
    assert PayoutAccount.__tablename__ == "payout_accounts"
    assert "provider_account_id" in PayoutAccount.__table__.columns.keys()
    assert Payout.__tablename__ == "payouts"
    assert "commission_deducted" in Payout.__table__.columns.keys()
    assert PlatformConfig.__tablename__ == "platform_config"
    assert WebhookEvent.__tablename__ == "webhook_events"
    assert "stripe_customer_id" in User.__table__.columns.keys()
    assert "transaction_id" in License.__table__.columns.keys()
