"""Integration tests for the Module 4 review-workspace migration and seed."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.modules.attestation import rubrics
from app.modules.attestation.models import (
    AttestationRubricDimension,
    AttestationRubricMethodology,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the integration database is upgraded to alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


async def test_rubric_dimensions_seeded(migrated_database) -> None:
    """All review-type rubric dimensions and methodology rows are seeded."""
    del migrated_database
    await engine.dispose()

    expected_dimensions = sum(
        len(dimensions) for dimensions in rubrics.RUBRICS.values()
    )
    async with async_session_factory() as session:
        dimension_count = await session.scalar(
            select(func.count()).select_from(AttestationRubricDimension)
        )
        methodology_count = await session.scalar(
            select(func.count()).select_from(AttestationRubricMethodology)
        )

    await engine.dispose()

    assert dimension_count == expected_dimensions
    assert methodology_count == len(rubrics.METHODOLOGY)
