"""Unit tests for the framework-locking artifact budget helper."""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact


async def _truncate() -> None:
    """Clear the tables this suite seeds."""
    async with async_session_factory() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE "
                f"{Artifact.__tablename__}, {Framework.__tablename__}, "
                f"{User.__tablename__} RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()


@pytest.fixture
async def budget_ctx(
    migrated_database: None,
) -> AsyncIterator[tuple[AsyncSession, Framework, Artifact]]:
    """Seed a framework with one 400MB artifact."""
    await engine.dispose()
    await _truncate()
    session = async_session_factory()
    contributor = User(
        email="budget@auracles.space",
        display_name="Budget",
        email_verified=True,
        password_hash=None,
    )
    framework = Framework(
        contributor_id=uuid4(),
        title="Budget Framework",
        description="Budget helper test framework.",
        category="framework",
        sector="financial_services",
        industry="fund_management",
        business_function="risk_management",
        tags=["b"],
        tags_text="b",
        jurisdiction="us",
        complexity=3,
        org_size="mid_market",
        lifecycle_stage="scale",
        price=Decimal("10.00"),
        currency="USD",
        license_types=["single_user"],
        commercial_rights="x",
        usage_restrictions="x",
        status="draft",
    )
    artifact = Artifact(
        framework_id=uuid4(),
        name="big.pdf",
        file_key="frameworks/fw/artifacts/big.pdf",
        file_size=400 * 1024 * 1024,
        mime_type="application/pdf",
    )
    async with session.begin():
        session.add(contributor)
        await session.flush()
        framework.contributor_id = contributor.id
        session.add(framework)
        await session.flush()
        artifact.framework_id = framework.id
        session.add(artifact)
        await session.flush()
    yield session, framework, artifact
    await session.close()
    await _truncate()
    await engine.dispose()


@pytest.mark.asyncio
async def test_reserve_rejects_over_budget(
    budget_ctx: tuple[AsyncSession, Framework, Artifact],
) -> None:
    """Adding 200MB on top of an existing 400MB artifact exceeds 500MB → 413."""
    from app.modules.frameworks import service

    db, framework, _artifact = budget_ctx
    with pytest.raises(HTTPException) as exc:
        await service._reserve_artifact_budget(
            db, framework.id, add_bytes=200 * 1024 * 1024, exclude_id=None
        )
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_reserve_excludes_replaced_artifact(
    budget_ctx: tuple[AsyncSession, Framework, Artifact],
) -> None:
    """Replacing the 400MB artifact leaves room, so 200MB is allowed."""
    from app.modules.frameworks import service

    db, framework, artifact = budget_ctx
    # Excluding the artifact being replaced must not raise.
    await service._reserve_artifact_budget(
        db, framework.id, add_bytes=200 * 1024 * 1024, exclude_id=artifact.id
    )
