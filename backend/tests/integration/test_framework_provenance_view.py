"""Owner/admin framework provenance view tests for Module 6c."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.modules.attestation.models import Attestation, AttestationBadge
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Delete rows used by framework provenance integration tests."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestationBadge))
            await session.execute(delete(Attestation))
            await session.execute(delete(Framework))
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the database is upgraded to the current alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database: None) -> AsyncIterator[None]:
    """Reset state before and after each framework provenance test."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


async def _create_user(email: str, roles: list[str]) -> UUID:
    """Create a verified user with approved role rows."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            for role in roles:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        approved_at=datetime.now(UTC),
                    )
                )
        return user.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for an authenticated test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def _create_framework(contributor_id: UUID, *, title: str) -> Framework:
    """Create one published framework for provenance reads."""
    async with async_session_factory() as session:
        framework = Framework(
            id=uuid4(),
            contributor_id=contributor_id,
            title=title,
            description="Published framework for provenance view tests.",
            version="1.0",
            status="published",
            category="framework",
            tags=["provenance"],
            price=Decimal("499.00"),
            license_types=["single_user"],
            published_at=datetime.now(UTC),
        )
        session.add(framework)
        await session.commit()
        await session.refresh(framework)
        return framework


async def _create_badge(
    *,
    framework: Framework,
    attestor_id: UUID,
    outcome: str,
    issued_at: datetime,
) -> None:
    """Create one attestation plus immutable badge row for provenance reads."""
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="framework",
                target_id=framework.id,
                requestor_id=framework.contributor_id,
                attestor_id=attestor_id,
                status="closed",
                outcome=outcome,
                review_type="quality",
                requested_specializations=["governance"],
                requested_jurisdictions=["US"],
                fee_amount=Decimal("500.00"),
                currency="USD",
                report_published_eligible=True,
                closed_at=issued_at,
            )
            session.add(attestation)
            await session.flush()
            session.add(
                AttestationBadge(
                    attestation_id=attestation.id,
                    framework_id=framework.id,
                    review_type="quality",
                    outcome=outcome,
                    attestor_id=attestor_id,
                    attestor_display_name="Provenance Attestor",
                    credentials_snapshot=[],
                    framework_version="1.0",
                    issued_at=issued_at,
                )
            )


@pytest.fixture
async def framework_with_mixed_badges(clean_state: None) -> tuple[Framework, UUID]:
    """Create a published framework with approved and rejected badge rows."""
    del clean_state
    owner_id = await _create_user("framework-owner@auracles.space", ["contributor"])
    attestor_id = await _create_user("provenance-attestor@auracles.space", ["attestor"])
    framework = await _create_framework(owner_id, title="Framework Provenance Target")
    await _create_badge(
        framework=framework,
        attestor_id=attestor_id,
        outcome="approved",
        issued_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    await _create_badge(
        framework=framework,
        attestor_id=attestor_id,
        outcome="rejected",
        issued_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    return framework, owner_id


@pytest.fixture
async def some_user(clean_state: None) -> UUID:
    """Create an authenticated contributor for missing-framework assertions."""
    del clean_state
    return await _create_user("some-contributor@auracles.space", ["contributor"])


async def test_owner_sees_all_outcomes_including_rejected(
    client,
    framework_with_mixed_badges: tuple[Framework, UUID],
) -> None:
    """The framework owner sees every badge, including rejected provenance."""
    framework, owner_id = framework_with_mixed_badges

    response = await client.get(
        f"/v1/frameworks/{framework.id}/attestation-badges",
        headers=auth_headers(owner_id, ["contributor"]),
    )

    assert response.status_code == 200
    outcomes = {badge["outcome"] for badge in response.json()}
    assert "rejected" in outcomes and "approved" in outcomes


async def test_non_owner_non_admin_forbidden(
    client,
    framework_with_mixed_badges: tuple[Framework, UUID],
) -> None:
    """A stranger cannot read another framework's provenance."""
    framework, _owner_id = framework_with_mixed_badges
    stranger_id = await _create_user("provenance-stranger@auracles.space", ["operator"])

    response = await client.get(
        f"/v1/frameworks/{framework.id}/attestation-badges",
        headers=auth_headers(stranger_id, ["operator"]),
    )

    assert response.status_code == 403


async def test_missing_framework_returns_404(client, some_user: UUID) -> None:
    """An unknown framework id returns 404."""
    response = await client.get(
        f"/v1/frameworks/{uuid4()}/attestation-badges",
        headers=auth_headers(some_user, ["contributor"]),
    )

    assert response.status_code == 404
