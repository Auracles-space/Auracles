"""Migration coverage for Module 3 AMM matching schema.

Verifies the nullable score-persistence columns on attestation offers and the
CoI reminder timestamp on attestor profiles are added on upgrade and removed on
downgrade.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from app.core.config import get_settings

PRIOR_HEAD = "2026_06_30_0046"


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


def test_amm_matching_schema_added(migrated_engine: Engine) -> None:
    """Upgrade adds offer score fields and the CoI reminder timestamp."""
    inspector = inspect(migrated_engine)
    offer_cols = {
        column["name"] for column in inspector.get_columns("attestation_offers")
    }
    profile_cols = {
        column["name"] for column in inspector.get_columns("attestor_profiles")
    }

    assert {"match_score", "score_breakdown"}.issubset(offer_cols)
    assert "coi_reminder_sent_at" in profile_cols


def test_downgrade_reverts_amm_matching_schema() -> None:
    """Downgrade removes the new nullable AMM-matching columns."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")
    command.downgrade(alembic_config, PRIOR_HEAD)
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PRIOR_HEAD)
    try:
        inspector = inspect(engine)
        offer_cols = {
            column["name"] for column in inspector.get_columns("attestation_offers")
        }
        profile_cols = {
            column["name"] for column in inspector.get_columns("attestor_profiles")
        }

        assert "match_score" not in offer_cols
        assert "score_breakdown" not in offer_cols
        assert "coi_reminder_sent_at" not in profile_cols
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
