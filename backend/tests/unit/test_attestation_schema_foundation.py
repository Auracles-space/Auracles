"""Migration coverage for Phase 4b Slice 1 attestation schema foundation.

Slice 1 creates the durable Attestation tables and admin-managed configuration
defaults that later request, matching, reporting, and dispute slices depend on.
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
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestationUploadSession,
    Credential,
)

PHASE_FOUR_A_HEAD = "2026_06_10_0012"

# The individual attestor_applications / attestor_profiles tables and their
# attestor_application_status_enum were retired in the org-attestor drop
# migration (2026_07_06_0068); the head schema no longer carries them.
ATTESTATION_TABLES = {
    "credentials",
    "attestations",
    "attestation_offers",
    "attestation_disputes",
    "attestation_upload_sessions",
}
ATTESTATION_ENUMS = {
    "attestation_target_enum",
    "attestation_status_enum",
    "attestation_outcome_enum",
    "attestation_offer_status_enum",
    "attestation_dispute_status_enum",
    # Module 5 replaced the release/refund/split resolution enum with a
    # category enum (intake) and an outcome enum (resolution).
    "attestation_dispute_category_enum",
    "attestation_dispute_outcome_enum",
    "attestation_upload_purpose_enum",
    "attestation_upload_scan_status_enum",
    "attestation_review_type_enum",
}
ATTESTATION_CONFIG_SEEDS = {
    "attestation_fee_framework": "250.00",
    "attestation_fee_contributor": "300.00",
    "attestation_fee_operator": "300.00",
    "attestation_fee_credential": "100.00",
    "attestation_fee_review_quality": "500.00",
    "attestation_fee_review_compliance": "1200.00",
    "attestation_fee_review_expert": "2500.00",
    "attestation_fee_review_provenance": "500.00",
    "attestation_cohort_size": "3",
    "attestation_completion_sla_days_framework": "10",
    "attestation_completion_sla_days_contributor": "10",
    "attestation_completion_sla_days_operator": "10",
    "attestation_completion_sla_days_credential": "10",
    "attestation_offer_accept_hours": "48",
    "attestation_dispute_window_business_days": "5",
}


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Run Phase 4b schema migrations and restore the local DB afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.downgrade(alembic_config, PHASE_FOUR_A_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PHASE_FOUR_A_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_attestation_migration_creates_tables_enums_indexes_and_seed_config(
    migrated_engine: Engine,
) -> None:
    """Alembic creates the Phase 4b Slice 1 attestation schema contract."""
    inspector = inspect(migrated_engine)

    with migrated_engine.connect() as connection:
        enum_names = {
            row[0]
            for row in connection.execute(
                text("SELECT typname FROM pg_type WHERE typname LIKE '%_enum'")
            )
        }
        config_rows = {
            row.key: row.value
            for row in connection.execute(
                text("SELECT key, value FROM platform_config")
            )
        }

    attestation_indexes = {
        index["name"] for index in inspector.get_indexes("attestations")
    }
    upload_indexes = {
        index["name"] for index in inspector.get_indexes("attestation_upload_sessions")
    }

    assert ATTESTATION_TABLES.issubset(set(inspector.get_table_names()))
    assert ATTESTATION_ENUMS.issubset(enum_names)
    assert ATTESTATION_CONFIG_SEEDS.items() <= config_rows.items()
    assert {
        "idx_attestations_target",
        "idx_attestations_status_dispute_window",
        "idx_attestations_status_completion_due",
    }.issubset(attestation_indexes)
    assert {
        "idx_attestation_upload_sessions_attestation_user_consumed",
        "idx_attestation_upload_sessions_credential_user_consumed",
        "idx_attestation_upload_sessions_expires_at",
        "idx_attestation_upload_sessions_scan_status",
    }.issubset(upload_indexes)


def test_attestation_migration_preserves_key_constraints(
    migrated_engine: Engine,
) -> None:
    """The schema exposes the invariants later attestation services rely on."""
    inspector = inspect(migrated_engine)

    attestation_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("attestations")
    }
    upload_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("attestation_upload_sessions")
    }
    offer_uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("attestation_offers")
    }
    upload_uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            "attestation_upload_sessions"
        )
    }

    assert {
        # Renamed by 2026_08_11_0094: the USD-only check became an allowlist of
        # the currencies the payment adapters can settle.
        "ck_attestations_currency_settleable",
        "ck_attestations_fee_amount_positive",
    }.issubset(attestation_checks)
    assert "ck_attestation_upload_sessions_single_parent" in upload_checks
    assert "uq_attestation_offers_attestation_org" in offer_uniques
    assert "uq_attestation_upload_sessions_s3_key" in upload_uniques


def test_attestation_migration_downgrade_removes_slice_one_schema() -> None:
    """Downgrade removes Phase 4b Slice 1 tables, enums, and seed rows cleanly."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PHASE_FOUR_A_HEAD)
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

        assert ATTESTATION_TABLES.isdisjoint(table_names)
        assert ATTESTATION_ENUMS.isdisjoint(enum_names)
        assert set(ATTESTATION_CONFIG_SEEDS).isdisjoint(config_keys)
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_attestation_orm_models_bind_to_slice_one_tables() -> None:
    """ORM models expose stable metadata for later attestation service slices."""
    configure_mappers()

    assert Credential.__tablename__ == "credentials"
    assert "evidence_file_keys" in Credential.__table__.columns.keys()
    assert Attestation.__tablename__ == "attestations"
    assert {"requested_specializations", "closed_at", "escrow_id"}.issubset(
        Attestation.__table__.columns.keys()
    )
    assert AttestationOffer.__tablename__ == "attestation_offers"
    assert AttestationDispute.__tablename__ == "attestation_disputes"
    assert AttestationUploadSession.__tablename__ == "attestation_upload_sessions"
    assert "scan_status" in AttestationUploadSession.__table__.columns.keys()
