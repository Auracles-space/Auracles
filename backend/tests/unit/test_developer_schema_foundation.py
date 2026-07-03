"""Migration coverage for Phase 5a Slice 1 developer schema foundation.

The developer platform depends on durable application, API key, commission,
payout, webhook, and request-log tables before service endpoints are added.
These tests keep that database contract explicit.
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
from app.modules.developer.models import (
    ApiKey,
    ApiRequestLog,
    DeveloperAccount,
    DeveloperApplication,
    PartnerCommission,
    PartnerPayout,
    PartnerPurchaseAttribution,
    PartnerWebhook,
    PartnerWebhookDelivery,
)

PHASE_FOUR_HEAD = "2026_06_11_0016"

DEVELOPER_TABLES = {
    "developer_applications",
    "developer_accounts",
    "api_keys",
    "api_request_logs",
    "partner_commissions",
    "partner_purchase_attributions",
    "partner_payouts",
    "partner_webhooks",
    "partner_webhook_deliveries",
}
DEVELOPER_ENUMS = {
    "developer_application_status_enum",
    "developer_account_status_enum",
    "api_key_status_enum",
    "partner_commission_status_enum",
    "webhook_delivery_status_enum",
}
DEVELOPER_CONFIG_SEEDS = {
    "partner_tier_thresholds": (
        '{"1":{"min":0,"max":99,"rate":"0.05"},'
        '"2":{"min":100,"max":499,"rate":"0.08"},'
        '"3":{"min":500,"max":null,"rate":"0.12"}}'
    ),
    "partner_min_payout_usd": "50",
    "partner_api_log_retention_days": "90",
}


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Run Phase 5a schema migrations and restore the local DB afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.downgrade(alembic_config, PHASE_FOUR_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PHASE_FOUR_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_developer_migration_creates_tables_enums_role_and_seed_config(
    migrated_engine: Engine,
) -> None:
    """Alembic creates the Phase 5a Slice 1 developer schema contract."""
    inspector = inspect(migrated_engine)

    with migrated_engine.connect() as connection:
        enum_names = {
            row[0]
            for row in connection.execute(
                text("SELECT typname FROM pg_type WHERE typname LIKE '%_enum'")
            )
        }
        role_labels = {
            row[0]
            for row in connection.execute(
                text(
                    """
                    SELECT enumlabel
                    FROM pg_enum
                    JOIN pg_type ON pg_type.oid = pg_enum.enumtypid
                    WHERE pg_type.typname = 'role_enum'
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

    assert DEVELOPER_TABLES.issubset(set(inspector.get_table_names()))
    assert DEVELOPER_ENUMS.issubset(enum_names)
    assert "developer" in role_labels
    assert DEVELOPER_CONFIG_SEEDS.items() <= config_rows.items()


def test_developer_migration_preserves_partner_integrity_constraints(
    migrated_engine: Engine,
) -> None:
    """The schema exposes integrity constraints needed by later money slices."""
    inspector = inspect(migrated_engine)

    application_indexes = {
        index["name"] for index in inspector.get_indexes("developer_applications")
    }
    api_key_indexes = {index["name"] for index in inspector.get_indexes("api_keys")}
    commission_uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("partner_commissions")
    }
    attribution_uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            "partner_purchase_attributions"
        )
    }
    payout_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("partner_payouts")
    }
    commission_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("partner_commissions")
    }

    assert "uq_developer_applications_user_pending" in application_indexes
    assert {"idx_api_keys_developer_account", "idx_api_keys_hash"}.issubset(
        api_key_indexes
    )
    assert "uq_partner_commissions_transaction" in commission_uniques
    assert "uq_partner_purchase_attr_transaction" in attribution_uniques
    assert "ck_partner_payouts_amount_positive" in payout_checks
    assert {
        "ck_partner_commissions_sale_amount_positive",
        "ck_partner_commissions_commission_amount_nonnegative",
    }.issubset(commission_checks)


def test_developer_migration_downgrade_removes_slice_one_schema() -> None:
    """Downgrade removes developer tables, enums, and config rows cleanly."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PHASE_FOUR_HEAD)
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
            config_keys = {
                row[0]
                for row in connection.execute(text("SELECT key FROM platform_config"))
            }

        assert DEVELOPER_TABLES.isdisjoint(table_names)
        assert DEVELOPER_ENUMS.isdisjoint(enum_names)
        assert set(DEVELOPER_CONFIG_SEEDS).isdisjoint(config_keys)
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_developer_orm_models_bind_to_slice_one_tables() -> None:
    """ORM models expose stable metadata for later developer service slices."""
    configure_mappers()

    assert DeveloperApplication.__tablename__ == "developer_applications"
    assert {"company_name", "website", "use_case", "admin_feedback"}.issubset(
        DeveloperApplication.__table__.columns.keys()
    )
    assert DeveloperAccount.__tablename__ == "developer_accounts"
    assert {"commission_tier", "tier_rate", "tier_sales_count"}.issubset(
        DeveloperAccount.__table__.columns.keys()
    )
    assert ApiKey.__tablename__ == "api_keys"
    assert {"key_prefix", "key_hash", "scopes", "rate_limit_per_min"}.issubset(
        ApiKey.__table__.columns.keys()
    )
    assert ApiRequestLog.__tablename__ == "api_request_logs"
    assert PartnerCommission.__tablename__ == "partner_commissions"
    assert {"tier_at_sale", "tier_rate", "commission_amount"}.issubset(
        PartnerCommission.__table__.columns.keys()
    )
    assert PartnerPurchaseAttribution.__tablename__ == "partner_purchase_attributions"
    assert {"license_type", "tier_at_sale", "tier_rate"}.issubset(
        PartnerPurchaseAttribution.__table__.columns.keys()
    )
    assert PartnerPayout.__tablename__ == "partner_payouts"
    assert PartnerWebhook.__tablename__ == "partner_webhooks"
    assert PartnerWebhookDelivery.__tablename__ == "partner_webhook_deliveries"
