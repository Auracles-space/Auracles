"""Integration tests for attestation rating side effects."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.attestation import rating_service
from app.modules.attestation.models import (
    Attestation,
    AttestationRating,
)
from app.modules.auth.models import User, UserRole
from app.modules.organizations.models import (
    Organization,
    OrgAttestorProfile,
    OrgMember,
)
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure attestation rating source tables exist before the test runs."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean(migrated_database: None) -> AsyncIterator[None]:
    """Reset attestation rating rows in FK-safe order around each test."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(AttestationRating))
            await session.execute(delete(Attestation))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _seed_rateable_attestation() -> tuple[UUID, User, UUID]:
    """Create a stood org attestation and return (org_id, requestor, attestation_id)."""
    async with async_session_factory() as session:
        async with session.begin():
            owner = User(
                email=f"a-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Owner",
                email_verified=True,
            )
            requestor = User(
                email=f"r-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Requestor",
                email_verified=True,
            )
            session.add_all([owner, requestor])
            await session.flush()
            org = Organization(
                slug=f"rating-org-{uuid4().hex[:6]}",
                name="Rating Org LLP",
                country="US",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            member = OrgMember(org_id=org.id, user_id=owner.id, role="owner")
            session.add(member)
            session.add(
                OrgAttestorProfile(
                    org_id=org.id,
                    specializations=["ml"],
                    jurisdictions=["us"],
                    active=True,
                )
            )
            await session.flush()
            attestation = Attestation(
                requestor_id=requestor.id,
                attestor_org_id=org.id,
                reviewing_member_id=member.id,
                target_type="contributor",
                target_id=requestor.id,
                review_type="quality",
                status="closed",
                report_published_eligible=True,
                fee_amount=Decimal("300.00"),
                currency="USD",
            )
            session.add(attestation)
            await session.flush()

        await session.refresh(requestor)
        return org.id, requestor, attestation.id


async def test_submit_rating_enqueues_attestor_recompute(
    clean: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Submitting a rating enqueues a targeted attestor-org reputation recompute."""
    del clean
    calls: list[tuple[object, ...]] = []

    def capture(*args: object) -> None:
        """Record Celery dispatch arguments without hitting the broker."""
        calls.append(args)

    from app.workers.tasks import reputation as reputation_tasks

    monkeypatch.setattr(reputation_tasks.recompute_subject_task, "delay", capture)

    org_id, requestor, attestation_id = await _seed_rateable_attestation()
    async with async_session_factory() as session:
        await rating_service.submit_rating(
            db=session,
            requestor=requestor,
            attestation_id=attestation_id,
            stars=5,
            comment=None,
        )

    assert ("attestor_org", str(org_id)) in calls
