"""Migration coverage for Phase 5e Slice 1 reputation schema foundation.

These tests lock the durable reputation score table and seeded platform
configuration before the scoring engine and read APIs build on them.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import configure_mappers

from app.core.config import get_settings
from app.modules.reputation.models import ReputationScore

PHASE_5D_HEAD = "2026_06_12_0024"

# The config keys migration 2026_06_13_0025 seeds, and therefore the only ones
# its downgrade is responsible for removing.
#
# Asserting on this set rather than on the `reputation_%` prefix is the whole
# point. `reputation_weights_attestor` matches that prefix but belongs to no
# migration — an admin writes it at runtime through
# `admin.service.set_reputation_weights`. Under xdist the workers share a
# database per worker, so an admin test landing on this worker first left that
# row behind and this test blamed the downgrade for not deleting something it
# never seeded. It failed on one PR and passed on the next depending only on
# how pytest sharded the suite.
_MIGRATION_SEEDED_KEYS = frozenset(
    {
        "reputation_decay_halflife_days",
        "reputation_dispute_penalty",
        "reputation_min_activity_contributor",
        "reputation_min_activity_framework",
        "reputation_min_activity_operator",
        "reputation_prior",
        "reputation_prior_strength_k",
        "reputation_weights_contributor",
        "reputation_weights_framework",
        "reputation_weights_operator",
    }
)
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _platform_config_rows(engine: Engine) -> dict[str, str]:
    """Return the seeded reputation-related platform configuration rows."""
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT key, value FROM platform_config WHERE key LIKE 'reputation_%'")
        )
        return {row.key: row.value for row in rows}


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Run the reputation migration and restore the local database afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))

    command.downgrade(alembic_config, PHASE_5D_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PHASE_5D_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_reputation_migration_creates_table_and_seeds_platform_config(
    migrated_engine: Engine,
) -> None:
    """Alembic creates the score table, index, and seeded config rows."""
    inspector = inspect(migrated_engine)
    table_names = set(inspector.get_table_names())
    columns = {column["name"] for column in inspector.get_columns("reputation_scores")}
    indexes = {index["name"] for index in inspector.get_indexes("reputation_scores")}
    seeded = _platform_config_rows(migrated_engine)

    assert "reputation_scores" in table_names
    assert {
        "subject_type",
        "subject_id",
        "score",
        "components",
        "is_provisional",
    }.issubset(columns)
    assert "ix_reputation_subject_type_score" in indexes
    assert "reputation_weights_framework" in seeded
    assert "reputation_prior" in seeded


def test_reputation_migration_downgrade_removes_slice_one_schema() -> None:
    """Downgrade removes the reputation table and seeded config rows."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PHASE_5D_HEAD)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        seeded = _platform_config_rows(engine)

        assert "reputation_scores" not in table_names
        # Every key the migration seeded is gone. Rows the application wrote
        # are not its to delete, so their survival is correct, not a leak.
        assert _MIGRATION_SEEDED_KEYS.isdisjoint(seeded)
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_reputation_orm_model_binds_to_slice_one_table() -> None:
    """ORM metadata exposes the score table columns and constraints."""
    configure_mappers()

    assert ReputationScore.__tablename__ == "reputation_scores"
    assert {
        "subject_type",
        "subject_id",
        "score",
        "components",
        "is_provisional",
    }.issubset(ReputationScore.__table__.columns.keys())
