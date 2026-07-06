"""Migration coverage for Module 6b: attestor as a reputation subject.

Verifies the reputation subject-type CHECK admits ``attestor`` and the
``attestor_profiles`` table gains the sticky certification timestamp.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import get_settings

PRE_6B_HEAD = "2026_07_01_0053"
BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Upgrade the local test database to head for schema assertions."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))

    command.downgrade(alembic_config, PRE_6B_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PRE_6B_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_reputation_scores_accepts_attestor_subject(
    migrated_engine: Engine,
) -> None:
    """Upgrade widens the subject-type CHECK to accept attestors."""
    row_id = uuid4()
    subject_id = uuid4()

    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO reputation_scores "
                "(id, subject_type, subject_id, components, is_provisional) "
                "VALUES (:id, 'attestor', :subject_id, '{}'::jsonb, true)"
            ),
            {"id": row_id, "subject_id": subject_id},
        )
        connection.execute(
            text("DELETE FROM reputation_scores WHERE id = :id"),
            {"id": row_id},
        )


