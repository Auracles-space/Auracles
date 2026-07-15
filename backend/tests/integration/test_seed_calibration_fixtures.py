"""Integration test for the idempotent calibration-fixture seed."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, select

from app.core.database import async_session_factory, engine
from app.integrations import s3
from app.modules.attestation.models import AttestorTrialAnswerKey
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.scripts import seed_calibration_fixtures as seed

pytestmark = pytest.mark.asyncio

_TITLE = "Calibration: Quality Sample"


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure application tables exist."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def clean_state(migrated_database: None) -> AsyncIterator[None]:
    """Remove seeded fixtures + owner before and after each run."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            async with session.begin():
                fixture_ids = (
                    await session.scalars(
                        select(Framework.id).where(Framework.is_calibration.is_(True))
                    )
                ).all()
                if fixture_ids:
                    await session.execute(
                        delete(AttestorTrialAnswerKey).where(
                            AttestorTrialAnswerKey.framework_id.in_(fixture_ids)
                        )
                    )
                    await session.execute(
                        delete(Artifact).where(Artifact.framework_id.in_(fixture_ids))
                    )
                    await session.execute(
                        delete(Framework).where(Framework.id.in_(fixture_ids))
                    )
                await session.execute(
                    delete(User).where(User.email == seed._SEED_OWNER_EMAIL)
                )

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def test_seed_is_idempotent(
    clean_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running the seed twice yields exactly one fully-formed fixture."""
    uploaded: list[str] = []
    monkeypatch.setattr(
        s3.storage,
        "upload_bytes",
        lambda bucket, key, body, mime_type: uploaded.append(key),
    )

    async with async_session_factory() as session:
        async with session.begin():
            first = await seed.seed_calibration_fixtures(session)
        async with session.begin():
            second = await seed.seed_calibration_fixtures(session)

    assert first == [_TITLE]
    assert second == []
    assert len(uploaded) == 1

    async with async_session_factory() as session:
        fixture = await session.scalar(
            select(Framework).where(
                Framework.title == _TITLE, Framework.is_calibration.is_(True)
            )
        )
        assert fixture is not None
        artifact_count = await session.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(
                Artifact.framework_id == fixture.id,
                Artifact.scan_status == "clean",
            )
        )
        assert artifact_count == 1
        key_count = await session.scalar(
            select(func.count())
            .select_from(AttestorTrialAnswerKey)
            .where(AttestorTrialAnswerKey.framework_id == fixture.id)
        )
        assert key_count and key_count > 0
