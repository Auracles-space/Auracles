"""Migration smoke test for the calibration-trial schema.

Enforces that the new columns, enum value, and tables exist and are queryable
after the calibration-trial migration is applied.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.modules.attestation.models import (
    AttestorTrial,
    AttestorTrialAnswerKey,
    AttestorTrialRubricScore,
)
from app.modules.frameworks.models import Framework

PREVIOUS_HEAD = "2026_07_14_0083"
BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Upgrade the test database to head and restore it afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.downgrade(alembic_config, PREVIOUS_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        command.downgrade(alembic_config, PREVIOUS_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


@pytest.mark.asyncio
async def test_new_schema_objects_exist(migrated_database: None) -> None:
    """New columns, enum value, and tables are queryable after migration."""
    # The shared async engine is a module-level singleton with a real pool,
    # while pytest-asyncio gives each test its own event loop. A connection
    # pooled by an earlier test is bound to that test's dead loop, and
    # pool_pre_ping normally recycles it — but the ping runs on this loop and
    # can itself raise "got Future attached to a different loop" from inside
    # asyncpg. Disposing first guarantees a pool built on the current loop.
    # Same defence as test_organizations_service.py's fixture.
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(select(Framework.is_calibration).limit(1))
        await session.execute(
            select(
                AttestorTrial.score_pct,
                AttestorTrial.auto_result,
                AttestorTrial.submitted_at,
            ).limit(1)
        )
        await session.execute(select(AttestorTrialAnswerKey).limit(1))
        await session.execute(select(AttestorTrialRubricScore).limit(1))
