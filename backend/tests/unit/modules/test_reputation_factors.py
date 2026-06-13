"""DB-backed factor aggregator smoke test for frameworks.

Builds framework, license, and review rows inline (no shared factories) and
checks that the framework aggregator counts reviews and active-license adoption.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework, License, Review
from app.modules.reputation import factors
from app.modules.reputation.weights import load_config
from app.shared.models.audit_log import AuditLog


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure reputation source tables exist before the test runs."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def factor_test_context() -> AsyncIterator[None]:
    """Reset marketplace rows in dependency order around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(Review))
            await session.execute(delete(License))
            await session.execute(delete(Framework))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _create_user(email: str) -> UUID:
    """Create one verified user and return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status="verified",
            )
            session.add(user)
            await session.flush()
        return user.id


async def _create_framework(contributor_id: UUID) -> UUID:
    """Create one published framework and return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                id=uuid4(),
                contributor_id=contributor_id,
                title="Reputation Test Framework",
                description="Reputation aggregator smoke framework.",
                version="1.0.0",
                status="published",
                category="framework",
                sector="financial_services",
                industry="fund_management",
                business_function="risk_management",
                tags=["risk"],
                tags_text="risk",
                jurisdiction="us",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=Decimal("499.00"),
                currency="USD",
                license_types=["single_user"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
        return framework.id


async def _grant_license(framework_id: UUID, operator_id: UUID, *, status: str) -> UUID:
    """Grant one license in the given status and return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            license_row = License(
                id=uuid4(),
                framework_id=framework_id,
                operator_id=operator_id,
                license_type="single_user",
                status=status,
                version_at_grant="1.0.0",
            )
            session.add(license_row)
        return license_row.id


async def _create_review(
    framework_id: UUID, operator_id: UUID, license_id: UUID, *, score: int
) -> None:
    """Create one review row for the framework."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Review(
                    id=uuid4(),
                    framework_id=framework_id,
                    operator_id=operator_id,
                    license_id=license_id,
                    score=score,
                )
            )


@pytest.mark.asyncio
async def test_framework_factors_reviews_and_adoption(
    migrated_database: None,
    factor_test_context: None,
) -> None:
    """Framework aggregator counts every review but only active-license adoption."""
    contributor_id = await _create_user("rep-contributor@example.com")
    op_one = await _create_user("rep-op1@example.com")
    op_two = await _create_user("rep-op2@example.com")
    fw_id = await _create_framework(contributor_id)

    # op_one keeps an active license (adoption=1); op_two's license expired.
    lic_one = await _grant_license(fw_id, op_one, status="active")
    lic_two = await _grant_license(fw_id, op_two, status="expired")
    await _create_review(fw_id, op_one, lic_one, score=5)
    await _create_review(fw_id, op_two, lic_two, score=4)

    async with async_session_factory() as session:
        cfg = await load_config(session, subject_type="framework")
        result = await factors.framework_factors(session, fw_id, cfg)

    assert result["reviews"].evidence == 2
    assert result["reviews"].value > 0
    assert result["adoption"].evidence == 1
