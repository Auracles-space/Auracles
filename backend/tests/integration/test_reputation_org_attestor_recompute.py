"""Integration: organization reputation recompute and public-read paths."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.attestation import directory_service
from app.modules.attestation.models import (
    Attestation,
    AttestationRating,
)
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework, License, Review
from app.modules.organizations.models import (
    Organization,
    OrgAttestorProfile,
    OrgCapability,
    OrgContributorProfile,
    OrgMember,
)
from app.modules.projects.models import Milestone, Project, Proposal
from app.modules.reputation import service as reputation_service
from app.modules.reputation.models import ReputationScore
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import reputation as reputation_tasks

pytestmark = pytest.mark.asyncio


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
async def clean(migrated_database: None) -> AsyncIterator[None]:
    """Reset reputation and org attestation rows in FK-safe order per test."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(ReputationScore))
            await session.execute(delete(Review))
            await session.execute(delete(License))
            await session.execute(delete(Framework))
            await session.execute(delete(Milestone))
            await session.execute(delete(Proposal))
            await session.execute(delete(Project))
            await session.execute(delete(AttestationRating))
            await session.execute(delete(Attestation))
            await session.execute(delete(OrgContributorProfile))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgCapability))
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


async def _seed_org(*, stars: list[int]) -> UUID:
    """Create an org attestor with stood attestations and requestor ratings."""
    async with async_session_factory() as session:
        async with session.begin():
            owner = User(
                email=f"o-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="O",
                email_verified=True,
            )
            requestor = User(
                email=f"r-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="R",
                email_verified=True,
            )
            session.add_all([owner, requestor])
            await session.flush()
            org = Organization(
                slug=f"rep-org-{uuid4().hex[:6]}",
                name="Recompute Org",
                country="US",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            session.add(
                OrgAttestorProfile(
                    org_id=org.id,
                    specializations=["ml"],
                    jurisdictions=["us"],
                    active=True,
                )
            )
            for stars_value in stars:
                attestation = Attestation(
                    requestor_id=requestor.id,
                    attestor_org_id=org.id,
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
                session.add(
                    AttestationRating(
                        attestation_id=attestation.id,
                        rated_by=requestor.id,
                        stars=stars_value,
                    )
                )
            return org.id


async def _seed_contributor_org(
    *,
    review_scores: list[int],
    completed_projects: int,
) -> UUID:
    """Create an org contributor with published reviews and closed project work."""
    async with async_session_factory() as session:
        async with session.begin():
            owner = User(
                email=f"co-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Contributor Owner",
                email_verified=True,
            )
            session.add(owner)
            await session.flush()
            org = Organization(
                slug=f"rep-contrib-{uuid4().hex[:6]}",
                name="Contributor Org",
                country="US",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            member = OrgMember(org_id=org.id, user_id=owner.id, role="owner")
            session.add(member)
            session.add(
                OrgCapability(
                    org_id=org.id,
                    capability="contributor",
                    status="active",
                )
            )
            session.add(OrgContributorProfile(org_id=org.id, active=True))
            await session.flush()
            framework = Framework(
                contributor_org_id=org.id,
                authoring_member_id=member.id,
                title="Reputation Framework",
                description="Org contributor reputation coverage.",
                version="1.0.0",
                status="published",
                category="framework",
                sector="financial_services",
                industry="fund_management",
                business_function="risk_management",
                tags=["reputation"],
                tags_text="reputation",
                jurisdiction="us",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=Decimal("499.00"),
                currency="USD",
                license_types=["single_user"],
            )
            session.add(framework)
            await session.flush()
            for score in review_scores:
                operator = User(
                    email=f"op-{uuid4().hex[:8]}@auracles.space",
                    password_hash=hash_password("CorrectHorse9"),
                    display_name="Operator",
                    email_verified=True,
                )
                session.add(operator)
                await session.flush()
                license_row = License(
                    id=uuid4(),
                    framework_id=framework.id,
                    operator_id=operator.id,
                    license_type="single_user",
                    status="active",
                    version_at_grant="1.0.0",
                )
                session.add(license_row)
                await session.flush()
                session.add(
                    Review(
                        framework_id=framework.id,
                        operator_id=operator.id,
                        license_id=license_row.id,
                        score=score,
                    )
                )
            for _ in range(completed_projects):
                project_operator = User(
                    email=f"proj-op-{uuid4().hex[:8]}@auracles.space",
                    password_hash=hash_password("CorrectHorse9"),
                    display_name="Project Operator",
                    email_verified=True,
                )
                session.add(project_operator)
                await session.flush()
                project = Project(
                    operator_id=project_operator.id,
                    title="Completed Project",
                    description="Closed project signal.",
                    category="framework_customization",
                    required_deliverables=[
                        {"name": "Memo", "description": "Closed memo"}
                    ],
                    budget_min=Decimal("1000.00"),
                    budget_max=Decimal("1200.00"),
                    currency="USD",
                    deadline=None,
                    status="closed",
                    milestone_plan_status="finalized",
                    expires_at=datetime.now(UTC),
                    closed_at=datetime.now(UTC),
                )
                session.add(project)
                await session.flush()
                proposal = Proposal(
                    project_id=project.id,
                    contributor_org_id=org.id,
                    delivering_member_id=member.id,
                    scope="Closed project scope.",
                    budget=Decimal("1000.00"),
                    currency="USD",
                    timeline_days=14,
                    deliverables=[{"name": "Memo", "description": "Closed memo"}],
                    status="accepted",
                    accepted_at=datetime.now(UTC),
                )
                session.add(proposal)
                await session.flush()
                project.accepted_proposal_id = proposal.id
                session.add(
                    Milestone(
                        project_id=project.id,
                        sequence=1,
                        name="Closed Milestone",
                        description="Completed milestone.",
                        budget=Decimal("1000.00"),
                        currency="USD",
                        status="approved",
                        funded_at=datetime.now(UTC),
                        approved_at=datetime.now(UTC),
                    )
                )
            return org.id


async def test_recompute_subject_scores_org_attestor(clean: None) -> None:
    """recompute_subject stores a non-provisional attestor_org score."""
    del clean
    org_id = await _seed_org(stars=[5, 5, 5, 4])

    await reputation_tasks.recompute_subject(
        subject_type="attestor_org",
        subject_id=org_id,
    )

    async with async_session_factory() as session:
        score = await reputation_service.get_score(
            session,
            subject_type="attestor_org",
            subject_id=org_id,
        )

    assert score is not None
    assert score.is_provisional is False
    assert score.score is not None
    assert score.score > Decimal("75")


async def test_recompute_certifies_org_on_merit(clean: None) -> None:
    """Enough high-rated stood attestations stamp the org's certification."""
    del clean
    org_id = await _seed_org(stars=[5] * 10)

    await reputation_tasks.recompute_subject(
        subject_type="attestor_org",
        subject_id=org_id,
    )

    async with async_session_factory() as session:
        profile = await session.scalar(
            select(OrgAttestorProfile).where(OrgAttestorProfile.org_id == org_id)
        )
    assert profile is not None
    assert profile.certified_attestor_at is not None


async def test_directory_reports_org_reputation_after_recompute(
    clean: None,
) -> None:
    """The public directory surfaces the org's number once it is non-provisional."""
    del clean
    org_id = await _seed_org(stars=[5, 5, 5, 4])

    async with async_session_factory() as session:
        before = await directory_service.get_directory_profile(session, org_id)
    assert before.reputation is None

    await reputation_tasks.recompute_subject(
        subject_type="attestor_org",
        subject_id=org_id,
    )

    async with async_session_factory() as session:
        after = await directory_service.get_directory_profile(session, org_id)
    assert after.reputation is not None
    assert after.reputation > 75


async def test_recompute_reputation_counts_active_org_attestors(
    clean: None,
) -> None:
    """The daily sweep includes active org attestors in its returned counts."""
    del clean
    await _seed_org(stars=[5, 4, 5])

    await engine.dispose()
    result = await asyncio.to_thread(
        lambda: reputation_tasks.recompute_reputation.apply().get()
    )
    await engine.dispose()

    assert result["attestor_org"] == 1


async def test_recompute_reputation_updates_org_contributor_profile(
    clean: None,
) -> None:
    """The daily sweep writes org contributor reputation from reviews and delivery."""
    del clean
    org_id = await _seed_contributor_org(review_scores=[5], completed_projects=1)

    await engine.dispose()
    await asyncio.to_thread(lambda: reputation_tasks.recompute_reputation.apply().get())
    await engine.dispose()

    async with async_session_factory() as session:
        profile = await session.scalar(
            select(OrgContributorProfile).where(
                OrgContributorProfile.org_id == org_id
            )
        )
    assert profile is not None
    assert profile.reputation_score is not None
    assert Decimal(str(profile.reputation_score)) > Decimal("80")
