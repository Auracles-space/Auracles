"""Unit tests for organization-backed Project proposal and delivery behavior."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.organizations.dependencies import OrgContext
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from app.modules.organizations.service import remove_member
from app.modules.projects import milestone_service
from app.modules.projects import service as project_service
from app.modules.projects.models import Deliverable, Milestone, Project, Proposal
from app.modules.projects.schemas import DeliverableSubmitRequest
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for org Project tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        command.upgrade(alembic_config, "head")
        sync_engine.dispose()


@pytest.fixture
async def org_project_state() -> AsyncIterator[None]:
    """Reset Project and organization rows around each org Project test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete Project rows before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(Deliverable))
            await session.execute(delete(Milestone))
            await session.execute(delete(Project))
            await session.execute(delete(Proposal))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _create_user(prefix: str) -> User:
    """Create and return one verified user for org Project tests."""
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
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
            await session.refresh(user)
            return user


async def _create_organization(owner: User) -> Organization:
    """Create and return one organization with an owner membership."""
    async with async_session_factory() as session:
        async with session.begin():
            organization = Organization(
                slug=f"proposal-org-{uuid4().hex[:8]}",
                name="Proposal Seller Org",
                country="GB",
                created_by=owner.id,
            )
            session.add(organization)
            await session.flush()
            session.add(
                OrgMember(org_id=organization.id, user_id=owner.id, role="owner")
            )
            await session.refresh(organization)
            return organization


async def _add_member(org_id: UUID, user_id: UUID, *, role: str = "member") -> UUID:
    """Create and return one organization membership row id."""
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=org_id, user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            return member.id


async def _set_contributor_capability(org_id: UUID, *, status: str = "active") -> None:
    """Persist one contributor capability row for an organization."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=org_id,
                    capability="contributor",
                    status=status,
                )
            )


async def _create_project(operator_id: UUID) -> Project:
    """Create and return one open Project row."""
    async with async_session_factory() as session:
        async with session.begin():
            project = Project(
                operator_id=operator_id,
                title="Org Bid Project",
                description="A project used to test org proposal ownership.",
                category="operations",
                required_deliverables=[
                    {"name": "Playbook", "description": "Implementation guide"}
                ],
                budget_min=Decimal("1000.00"),
                budget_max=Decimal("2000.00"),
                currency="USD",
                expires_at=datetime.now(UTC),
            )
            session.add(project)
            await session.flush()
            await session.refresh(project)
            return project


async def _create_milestone(project_id: UUID) -> Milestone:
    """Create and return one pending Milestone."""
    async with async_session_factory() as session:
        async with session.begin():
            milestone = Milestone(
                project_id=project_id,
                sequence=1,
                name="Milestone 1",
                description="Initial milestone.",
                budget=Decimal("1000.00"),
                currency="USD",
            )
            session.add(milestone)
            await session.flush()
            await session.refresh(milestone)
            return milestone


async def _accept_proposal(project_id: UUID, proposal_id: UUID) -> None:
    """Mark a Proposal accepted and attach it to its Project."""
    async with async_session_factory() as session:
        async with session.begin():
            project = await session.get(Project, project_id)
            proposal = await session.get(Proposal, proposal_id)
            assert project is not None and proposal is not None
            project.status = "assigned"
            project.accepted_proposal_id = proposal.id
            proposal.status = "accepted"
            proposal.accepted_at = datetime.now(UTC)


async def _org_context(org_id: UUID, owner_id: UUID) -> OrgContext:
    """Build an OrgContext for the org owner."""
    async with async_session_factory() as session:
        org = await session.get(Organization, org_id)
        user = await session.get(User, owner_id)
        member = await session.scalar(
            select(OrgMember).where(
                OrgMember.org_id == org_id,
                OrgMember.user_id == owner_id,
            )
        )
        assert org is not None and user is not None and member is not None
        return OrgContext(org=org, member=member, user=user)


@pytest.mark.asyncio
async def test_project_org_seller_xor_rejects_both_and_neither(
    migrated_database: None,
    org_project_state: None,
) -> None:
    """Proposal and Deliverable persistence must reject invalid seller XOR rows."""
    del migrated_database, org_project_state
    operator = await _create_user("project-operator")
    contributor = await _create_user("project-contributor")
    organization = await _create_organization(contributor)
    project = await _create_project(operator.id)
    milestone = await _create_milestone(project.id)

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    Proposal(
                        project_id=project.id,
                        contributor_id=contributor.id,
                        contributor_org_id=organization.id,
                        scope="Org proposal scope that is long enough.",
                        budget=Decimal("1500.00"),
                        currency="USD",
                        timeline_days=14,
                        deliverables=[
                            {"name": "Operating model", "description": "Model"}
                        ],
                    )
                )
                await session.flush()

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    Proposal(
                        project_id=project.id,
                        contributor_id=None,
                        contributor_org_id=None,
                        scope="Org proposal scope that is long enough.",
                        budget=Decimal("1500.00"),
                        currency="USD",
                        timeline_days=14,
                        deliverables=[
                            {"name": "Operating model", "description": "Model"}
                        ],
                    )
                )
                await session.flush()

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    Deliverable(
                        milestone_id=milestone.id,
                        contributor_id=contributor.id,
                        contributor_org_id=organization.id,
                        name="Delivery pack",
                        description="Submitted delivery.",
                        file_keys=["workspace/file.txt"],
                    )
                )
                await session.flush()

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    Deliverable(
                        milestone_id=milestone.id,
                        contributor_id=None,
                        contributor_org_id=None,
                        name="Delivery pack",
                        description="Submitted delivery.",
                        file_keys=["workspace/file.txt"],
                    )
                )
                await session.flush()


@pytest.mark.asyncio
async def test_submit_org_proposal_stamps_org_and_delivering_member(
    migrated_database: None,
    org_project_state: None,
) -> None:
    """Submitting an org Proposal stamps org ownership and the staffed member."""
    del migrated_database, org_project_state
    operator = await _create_user("project-operator")
    owner = await _create_user("project-owner")
    delivery_user = await _create_user("project-delivery")
    organization = await _create_organization(owner)
    delivering_member_id = await _add_member(organization.id, delivery_user.id)
    await _set_contributor_capability(organization.id)
    project = await _create_project(operator.id)

    async with async_session_factory() as session:
        proposal = await project_service.submit_org_proposal(
            db=session,
            org_id=organization.id,
            actor_id=owner.id,
            project_id=project.id,
            delivering_member_id=delivering_member_id,
            scope="Org proposal scope that is long enough.",
            budget=Decimal("1500.00"),
            timeline_days=14,
            deliverables=[{"name": "Operating model", "description": "Model"}],
        )

    assert proposal.contributor_id is None
    assert proposal.contributor_org_id == organization.id
    assert proposal.delivering_member_id == delivering_member_id
    assert proposal.project_id == project.id


@pytest.mark.asyncio
async def test_submit_org_proposal_conflicts_when_org_already_has_live_bid(
    migrated_database: None,
    org_project_state: None,
) -> None:
    """An organization cannot hold two live Proposals on the same Project."""
    del migrated_database, org_project_state
    operator = await _create_user("project-operator")
    owner = await _create_user("project-owner")
    first_delivery_user = await _create_user("project-delivery-one")
    second_delivery_user = await _create_user("project-delivery-two")
    organization = await _create_organization(owner)
    first_member_id = await _add_member(organization.id, first_delivery_user.id)
    second_member_id = await _add_member(organization.id, second_delivery_user.id)
    await _set_contributor_capability(organization.id)
    project = await _create_project(operator.id)

    async with async_session_factory() as session:
        await project_service.submit_org_proposal(
            db=session,
            org_id=organization.id,
            actor_id=owner.id,
            project_id=project.id,
            delivering_member_id=first_member_id,
            scope="Org proposal scope that is long enough.",
            budget=Decimal("1500.00"),
            timeline_days=14,
            deliverables=[{"name": "Operating model", "description": "Model"}],
        )

    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await project_service.submit_org_proposal(
                db=session,
                org_id=organization.id,
                actor_id=owner.id,
                project_id=project.id,
                delivering_member_id=second_member_id,
                scope="A second org proposal scope that is long enough.",
                budget=Decimal("1600.00"),
                timeline_days=21,
                deliverables=[{"name": "Runbook", "description": "Runbook"}],
            )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_submit_org_proposal_rejects_self_deal_conflict(
    migrated_database: None,
    org_project_state: None,
) -> None:
    """An org cannot bid on a Project posted by one of its own members."""
    del migrated_database, org_project_state
    operator = await _create_user("project-operator")
    owner = await _create_user("project-owner")
    delivery_user = await _create_user("project-delivery")
    organization = await _create_organization(owner)
    await _add_member(organization.id, operator.id)
    delivering_member_id = await _add_member(organization.id, delivery_user.id)
    await _set_contributor_capability(organization.id)
    project = await _create_project(operator.id)

    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await project_service.submit_org_proposal(
                db=session,
                org_id=organization.id,
                actor_id=owner.id,
                project_id=project.id,
                delivering_member_id=delivering_member_id,
                scope="Org proposal scope that is long enough.",
                budget=Decimal("1500.00"),
                timeline_days=14,
                deliverables=[{"name": "Operating model", "description": "Model"}],
            )

    assert exc.value.status_code == 422
    assert exc.value.detail["error_code"] == "self_deal_conflict"


@pytest.mark.asyncio
async def test_submit_org_proposal_rejects_non_member_delivery_assignment(
    migrated_database: None,
    org_project_state: None,
) -> None:
    """The staffed delivery member must belong to the organization."""
    del migrated_database, org_project_state
    operator = await _create_user("project-operator")
    owner = await _create_user("project-owner")
    outsider = await _create_user("project-outsider")
    organization = await _create_organization(owner)
    await _set_contributor_capability(organization.id)
    project = await _create_project(operator.id)

    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await project_service.submit_org_proposal(
                db=session,
                org_id=organization.id,
                actor_id=owner.id,
                project_id=project.id,
                delivering_member_id=outsider.id,
                scope="Org proposal scope that is long enough.",
                budget=Decimal("1500.00"),
                timeline_days=14,
                deliverables=[{"name": "Operating model", "description": "Model"}],
            )

    assert exc.value.status_code == 422
    assert exc.value.detail["error_code"] == "delivering_member_invalid"


@pytest.mark.asyncio
async def test_submit_org_proposal_rejects_suspended_capability(
    migrated_database: None,
    org_project_state: None,
) -> None:
    """Suspended contributor capability blocks new organization Proposals."""
    del migrated_database, org_project_state
    operator = await _create_user("project-operator")
    owner = await _create_user("project-owner")
    staffed_user = await _create_user("project-delivery")
    organization = await _create_organization(owner)
    staffed_member_id = await _add_member(organization.id, staffed_user.id)
    await _set_contributor_capability(organization.id, status="suspended")
    project = await _create_project(operator.id)

    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await project_service.submit_org_proposal(
                db=session,
                org_id=organization.id,
                actor_id=owner.id,
                project_id=project.id,
                delivering_member_id=staffed_member_id,
                scope="Org proposal scope that is long enough.",
                budget=Decimal("1500.00"),
                timeline_days=14,
                deliverables=[{"name": "Operating model", "description": "Model"}],
            )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_reassign_delivering_member_before_start_ok_after_funding_conflicts(
    migrated_database: None,
    org_project_state: None,
) -> None:
    """Reassignment is allowed before funding starts and blocked after it."""
    del migrated_database, org_project_state
    operator = await _create_user("project-operator")
    owner = await _create_user("project-owner")
    first_delivery_user = await _create_user("project-delivery-one")
    second_delivery_user = await _create_user("project-delivery-two")
    organization = await _create_organization(owner)
    first_member_id = await _add_member(organization.id, first_delivery_user.id)
    second_member_id = await _add_member(organization.id, second_delivery_user.id)
    await _set_contributor_capability(organization.id)
    project = await _create_project(operator.id)

    async with async_session_factory() as session:
        proposal = await project_service.submit_org_proposal(
            db=session,
            org_id=organization.id,
            actor_id=owner.id,
            project_id=project.id,
            delivering_member_id=first_member_id,
            scope="Org proposal scope that is long enough.",
            budget=Decimal("1500.00"),
            timeline_days=14,
            deliverables=[{"name": "Operating model", "description": "Model"}],
        )
    await _accept_proposal(project.id, proposal.id)

    async with async_session_factory() as session:
        reassigned = await project_service.reassign_delivering_member(
            db=session,
            org_id=organization.id,
            actor_id=owner.id,
            proposal_id=proposal.id,
            delivering_member_id=second_member_id,
        )

    assert reassigned.delivering_member_id == second_member_id

    milestone = await _create_milestone(project.id)
    async with async_session_factory() as session:
        async with session.begin():
            project_row = await session.get(Project, project.id)
            milestone_row = await session.get(Milestone, milestone.id)
            assert project_row is not None and milestone_row is not None
            project_row.status = "in_progress"
            milestone_row.status = "funded"
            milestone_row.funded_at = datetime.now(UTC)

    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await project_service.reassign_delivering_member(
                db=session,
                org_id=organization.id,
                actor_id=owner.id,
                proposal_id=proposal.id,
                delivering_member_id=first_member_id,
            )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_remove_member_blocks_started_delivery_and_unassigns_unstarted(
    migrated_database: None,
    org_project_state: None,
) -> None:
    """Started delivery blocks removal; unstarted delivery is unstaffed."""
    del migrated_database, org_project_state
    operator = await _create_user("project-operator")
    owner = await _create_user("project-owner")
    started_user = await _create_user("project-delivery-started")
    unstarted_user = await _create_user("project-delivery-unstarted")
    organization = await _create_organization(owner)
    started_member_id = await _add_member(organization.id, started_user.id)
    unstarted_member_id = await _add_member(organization.id, unstarted_user.id)
    await _set_contributor_capability(organization.id)
    owner_ctx = await _org_context(organization.id, owner.id)

    started_project = await _create_project(operator.id)
    unstarted_project = await _create_project(operator.id)

    async with async_session_factory() as session:
        started_proposal = await project_service.submit_org_proposal(
            db=session,
            org_id=organization.id,
            actor_id=owner.id,
            project_id=started_project.id,
            delivering_member_id=started_member_id,
            scope="Org proposal scope that is long enough.",
            budget=Decimal("1500.00"),
            timeline_days=14,
            deliverables=[{"name": "Operating model", "description": "Model"}],
        )
    await _accept_proposal(started_project.id, started_proposal.id)
    started_milestone = await _create_milestone(started_project.id)
    async with async_session_factory() as session:
        async with session.begin():
            project_row = await session.get(Project, started_project.id)
            milestone_row = await session.get(Milestone, started_milestone.id)
            assert project_row is not None and milestone_row is not None
            project_row.status = "in_progress"
            milestone_row.status = "funded"
            milestone_row.funded_at = datetime.now(UTC)

    async with async_session_factory() as session:
        unstarted_proposal = await project_service.submit_org_proposal(
            db=session,
            org_id=organization.id,
            actor_id=owner.id,
            project_id=unstarted_project.id,
            delivering_member_id=unstarted_member_id,
            scope="Org proposal scope that is long enough.",
            budget=Decimal("1500.00"),
            timeline_days=14,
            deliverables=[{"name": "Operating model", "description": "Model"}],
        )
    await _accept_proposal(unstarted_project.id, unstarted_proposal.id)

    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await remove_member(
                session,
                context=owner_ctx,
                member_id=started_member_id,
            )
    assert exc.value.status_code == 409

    async with async_session_factory() as session:
        await remove_member(
            session,
            context=owner_ctx,
            member_id=unstarted_member_id,
        )

    async with async_session_factory() as session:
        proposal_row = await session.get(Proposal, unstarted_proposal.id)
        assert proposal_row is not None
        assert proposal_row.delivering_member_id is None


@pytest.mark.asyncio
async def test_delivering_member_can_submit_org_deliverable(
    migrated_database: None,
    org_project_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The staffed member can submit a Deliverable for accepted org work."""
    del migrated_database, org_project_state
    operator = await _create_user("project-operator")
    owner = await _create_user("project-owner")
    staffed_user = await _create_user("project-delivery")
    organization = await _create_organization(owner)
    staffed_member_id = await _add_member(organization.id, staffed_user.id)
    await _set_contributor_capability(organization.id)
    project = await _create_project(operator.id)

    def _noop_delay(*args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    def _noop_notify(*args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(milestone_service.scan_deliverable_upload, "delay", _noop_delay)
    monkeypatch.setattr(
        milestone_service.project_notifications,
        "notify_deliverable_submitted",
        _noop_notify,
    )

    async with async_session_factory() as session:
        proposal = await project_service.submit_org_proposal(
            db=session,
            org_id=organization.id,
            actor_id=owner.id,
            project_id=project.id,
            delivering_member_id=staffed_member_id,
            scope="Org proposal scope that is long enough.",
            budget=Decimal("1500.00"),
            timeline_days=14,
            deliverables=[{"name": "Operating model", "description": "Model"}],
        )
    await _accept_proposal(project.id, proposal.id)
    milestone = await _create_milestone(project.id)
    async with async_session_factory() as session:
        async with session.begin():
            project_row = await session.get(Project, project.id)
            milestone_row = await session.get(Milestone, milestone.id)
            assert project_row is not None and milestone_row is not None
            project_row.status = "in_progress"
            milestone_row.status = "funded"
            milestone_row.funded_at = datetime.now(UTC)

    async with async_session_factory() as session:
        deliverable = await milestone_service.submit_deliverable(
            db=session,
            contributor=staffed_user,
            project_id=project.id,
            milestone_id=milestone.id,
            payload=DeliverableSubmitRequest(
                name="Delivery pack",
                description="Submitted org delivery.",
                file_keys=["workspace/file.txt"],
            ),
        )

    assert deliverable.contributor_id is None
    assert deliverable.contributor_org_id == organization.id


@pytest.mark.asyncio
async def test_non_delivering_member_cannot_submit_org_deliverable(
    migrated_database: None,
    org_project_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the staffed member may submit Deliverables for org Project work."""
    del migrated_database, org_project_state
    operator = await _create_user("project-operator")
    owner = await _create_user("project-owner")
    staffed_user = await _create_user("project-delivery")
    other_member_user = await _create_user("project-other-delivery")
    organization = await _create_organization(owner)
    staffed_member_id = await _add_member(organization.id, staffed_user.id)
    await _add_member(organization.id, other_member_user.id)
    await _set_contributor_capability(organization.id)
    project = await _create_project(operator.id)

    def _noop_delay(*args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    def _noop_notify(*args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(milestone_service.scan_deliverable_upload, "delay", _noop_delay)
    monkeypatch.setattr(
        milestone_service.project_notifications,
        "notify_deliverable_submitted",
        _noop_notify,
    )

    async with async_session_factory() as session:
        proposal = await project_service.submit_org_proposal(
            db=session,
            org_id=organization.id,
            actor_id=owner.id,
            project_id=project.id,
            delivering_member_id=staffed_member_id,
            scope="Org proposal scope that is long enough.",
            budget=Decimal("1500.00"),
            timeline_days=14,
            deliverables=[{"name": "Operating model", "description": "Model"}],
        )
    await _accept_proposal(project.id, proposal.id)
    milestone = await _create_milestone(project.id)
    async with async_session_factory() as session:
        async with session.begin():
            project_row = await session.get(Project, project.id)
            milestone_row = await session.get(Milestone, milestone.id)
            assert project_row is not None and milestone_row is not None
            project_row.status = "in_progress"
            milestone_row.status = "funded"
            milestone_row.funded_at = datetime.now(UTC)

    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await milestone_service.submit_deliverable(
                db=session,
                contributor=other_member_user,
                project_id=project.id,
                milestone_id=milestone.id,
                payload=DeliverableSubmitRequest(
                    name="Delivery pack",
                    description="Submitted org delivery.",
                    file_keys=["workspace/file.txt"],
                ),
            )

    assert exc.value.status_code == 403
