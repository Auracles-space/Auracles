"""Migration coverage for Module 6c badge & provenance schema.

6c adds the immutable ``attestation_badges`` snapshot table and the
``attestations.framework_version_id`` capture FK.
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

PREVIOUS_HEAD = "2026_07_02_0054"
BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Run migrations to head and restore the DB afterwards."""
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


def test_badges_table_and_capture_fk_exist(migrated_engine: Engine) -> None:
    """Upgrade creates attestation_badges + attestations.framework_version_id."""
    inspector = inspect(migrated_engine)

    assert "attestation_badges" in inspector.get_table_names()

    badge_columns = {c["name"] for c in inspector.get_columns("attestation_badges")}
    assert {
        "id",
        "attestation_id",
        "framework_id",
        "review_type",
        "outcome",
        "attestor_id",
        "attestor_display_name",
        "credentials_snapshot",
        "framework_version",
        "issued_at",
        "created_at",
    }.issubset(badge_columns)

    unique_names = {
        c["name"] for c in inspector.get_unique_constraints("attestation_badges")
    }
    assert "uq_attestation_badges_attestation" in unique_names

    index_names = {i["name"] for i in inspector.get_indexes("attestation_badges")}
    assert {
        "idx_attestation_badges_framework",
        "idx_attestation_badges_attestor",
    }.issubset(index_names)

    attestation_columns = {c["name"] for c in inspector.get_columns("attestations")}
    assert "framework_version_id" in attestation_columns


def test_downgrade_removes_slice_schema() -> None:
    """Downgrade -1 drops the badges table and the capture FK cleanly."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))

    command.downgrade(alembic_config, PREVIOUS_HEAD)
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PREVIOUS_HEAD)
    try:
        inspector = inspect(engine)
        assert "attestation_badges" not in inspector.get_table_names()
        attestation_columns = {c["name"] for c in inspector.get_columns("attestations")}
        assert "framework_version_id" not in attestation_columns
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
