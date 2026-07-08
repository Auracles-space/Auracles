"""Attestor-org public Completed Attestations list (Module 6c, positive-only)."""

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
from app.core.security import hash_password
from app.modules.attestation.models import Attestation, AttestationBadge
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework
from app.modules.organizations.models import Organization, OrgMember
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Delete rows used by attestor-org completed-list tests, FK-safe."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestationBadge))
            await session.execute(delete(Attestation))
            await session.execute(delete(Framework))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
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
    """Reset state before and after each completed-list test."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


async def _create_user(email: str, roles: list[str]) -> UUID:
    """Create a verified user for completed-list tests."""
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


async def _create_attestor_org(owner_id: UUID) -> UUID:
    """Create one organization owned by ``owner_id``; return the org id."""
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"completed-org-{uuid4().hex[:6]}",
                name="Completed Attestor Org",
                country="US",
                created_by=owner_id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner_id, role="owner"))
            return org.id


async def _create_framework(contributor_id: UUID, *, title: str) -> Framework:
    """Create one published framework whose title can be joined into the list."""
    async with async_session_factory() as session:
        framework = Framework(
            id=uuid4(),
            contributor_id=contributor_id,
            title=title,
            description="Published framework for attestor completed-list tests.",
            version="1.0",
            status="published",
            category="framework",
            tags=["completed"],
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
    org_id: UUID,
    outcome: str,
    issued_at: datetime,
) -> None:
    """Create one org attestation row plus its immutable badge snapshot."""
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="framework",
                target_id=framework.id,
                requestor_id=framework.contributor_id,
                attestor_org_id=org_id,
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
                    attestor_org_id=org_id,
                    attestor_org_slug="completed-org",
                    verification_level=2,
                    attestor_display_name="Completed Attestor Org",
                    credentials_snapshot=[],
                    framework_version="1.0",
                    issued_at=issued_at,
                )
            )


@pytest.fixture
async def org_with_completed_badges(clean_state: None) -> UUID:
    """Create one attestor org with approved and rejected completed badge rows."""
    del clean_state
    contributor_id = await _create_user(
        "completed-framework-owner@auracles.space",
        ["contributor"],
    )
    owner_id = await _create_user(
        "completed-org-owner@auracles.space",
        ["attestor"],
    )
    org_id = await _create_attestor_org(owner_id)
    approved_framework = await _create_framework(
        contributor_id,
        title="Approved Completed Framework",
    )
    rejected_framework = await _create_framework(
        contributor_id,
        title="Rejected Completed Framework",
    )
    await _create_badge(
        framework=approved_framework,
        org_id=org_id,
        outcome="approved",
        issued_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    await _create_badge(
        framework=rejected_framework,
        org_id=org_id,
        outcome="rejected",
        issued_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    return org_id


async def test_lists_positive_completed_with_framework_title(
    client,
    org_with_completed_badges: UUID,
) -> None:
    """Public list returns the org's positive badges with framework titles."""
    response = await client.get(
        f"/v1/attestor-orgs/{org_with_completed_badges}/completed"
    )

    assert response.status_code == 200
    body = response.json()
    outcomes = {entry["outcome"] for entry in body}
    assert outcomes == {"approved"}
    assert all(entry["framework_title"] for entry in body)
