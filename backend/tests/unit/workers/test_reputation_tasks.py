"""recompute_reputation task tests.

Drives the plain-async `recompute_subject` helper directly (the Celery wrappers
just call it) and checks the score is persisted, non-provisional with enough
evidence, and stable across reruns.
"""

from __future__ import annotations

import asyncio
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
from app.modules.reputation import service as reputation_service
from app.modules.reputation.models import ReputationScore
from app.shared.models.audit_log import AuditLog
from app.workers.tasks.reputation import (
    recompute_reputation,
    recompute_subject,
    recompute_subject_task,
)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure reputation + source tables exist before the test runs."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def reputation_test_context() -> AsyncIterator[None]:
    """Reset reputation + marketplace rows in dependency order around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(ReputationScore))
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


async def _create_published_framework(contributor_id: UUID) -> UUID:
    """Create one published framework and return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                id=uuid4(),
                contributor_id=contributor_id,
                title="Recompute Test Framework",
                description="Recompute task smoke framework.",
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


async def _grant_active_license_and_review(
    framework_id: UUID, operator_id: UUID, *, score: int
) -> None:
    """Grant one active license and a matching review for the operator."""
    async with async_session_factory() as session:
        async with session.begin():
            license_row = License(
                id=uuid4(),
                framework_id=framework_id,
                operator_id=operator_id,
                license_type="single_user",
                status="active",
                version_at_grant="1.0.0",
            )
            session.add(license_row)
            await session.flush()
            session.add(
                Review(
                    id=uuid4(),
                    framework_id=framework_id,
                    operator_id=operator_id,
                    license_id=license_row.id,
                    score=score,
                )
            )


@pytest.mark.asyncio
async def test_recompute_subject_upserts_and_is_idempotent(
    migrated_database: None,
    reputation_test_context: None,
) -> None:
    """Recompute persists a non-provisional score and reruns produce the same score."""
    contributor_id = await _create_user("recompute-contributor@example.com")
    fw_id = await _create_published_framework(contributor_id)
    # 2 reviews + 2 active licenses → evidence 4 ≥ framework min_activity 3.
    for index in range(2):
        operator_id = await _create_user(f"recompute-op{index}@example.com")
        await _grant_active_license_and_review(fw_id, operator_id, score=5)

    await recompute_subject(subject_type="framework", subject_id=fw_id)
    async with async_session_factory() as session:
        first = await reputation_service.get_score(
            session, subject_type="framework", subject_id=fw_id
        )
    assert first is not None
    assert first.is_provisional is False
    assert first.score is not None

    await recompute_subject(subject_type="framework", subject_id=fw_id)
    async with async_session_factory() as session:
        second = await reputation_service.get_score(
            session, subject_type="framework", subject_id=fw_id
        )
    assert second is not None
    assert second.score == first.score


async def _add_role(user_id: UUID, role: str) -> None:
    """Approve one role for a user so the batch recompute enumerates them."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                UserRole(user_id=user_id, role=role, approved_at=datetime.now(UTC))
            )


@pytest.mark.asyncio
async def test_recompute_reputation_batch_scores_every_subject_type(
    migrated_database: None,
    reputation_test_context: None,
) -> None:
    """The daily Beat task recomputes every reputation subject type.

    Runs the Celery wrapper through ``asyncio.to_thread`` so its worker event
    loop is isolated from the test loop, with the shared engine disposed around
    the hop.
    """
    contributor_id = await _create_user("batch-contributor@example.com")
    await _add_role(contributor_id, "contributor")
    operator_id = await _create_user("batch-operator@example.com")
    await _add_role(operator_id, "operator")
    fw_id = await _create_published_framework(contributor_id)
    await _grant_active_license_and_review(fw_id, operator_id, score=5)

    await engine.dispose()
    result = await asyncio.to_thread(lambda: recompute_reputation.apply().get())
    await engine.dispose()

    assert result == {
        "framework": 1,
        "contributor": 1,
        "operator": 1,
        "attestor_org": 0,
    }

    async with async_session_factory() as session:
        framework_score = await reputation_service.get_score(
            session, subject_type="framework", subject_id=fw_id
        )
    assert framework_score is not None


@pytest.mark.asyncio
async def test_recompute_subject_task_wrapper_completes(
    migrated_database: None,
    reputation_test_context: None,
) -> None:
    """The admin single-subject recompute wrapper scores one framework."""
    contributor_id = await _create_user("single-contributor@example.com")
    fw_id = await _create_published_framework(contributor_id)

    await engine.dispose()
    result = await asyncio.to_thread(
        lambda: recompute_subject_task.apply(args=["framework", str(fw_id)]).get()
    )
    await engine.dispose()

    assert result == {"status": "completed"}
