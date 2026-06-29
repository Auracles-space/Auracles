"""Shared fixtures for `tests/unit/modules/` service- and model-level tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from tests.support.db_cleanup import clear_identity_state_sync


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the test database is at alembic head and identity state is clean.

    Mirrors the fixture used by `tests/unit/test_bootstrap_admin.py` and
    `tests/integration/test_attestor_applications.py` so model/service tests
    under `tests/unit/modules/` can rely on a known-good schema without
    duplicating the upgrade + cleanup logic per test module.
    """
    engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    with Session(engine) as session:
        clear_identity_state_sync(session)
        session.commit()
    try:
        yield
    finally:
        with Session(engine) as session:
            clear_identity_state_sync(session)
            session.commit()
        engine.dispose()
