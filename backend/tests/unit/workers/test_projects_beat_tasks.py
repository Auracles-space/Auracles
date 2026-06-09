"""Tests for Phase 4a Project Beat tasks."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.auth.models import User, UserRole
from app.modules.projects.models import Project, Proposal, ProposalAmendment
from app.modules.workspace.models import WorkspaceMessage
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import projects_beat


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Project tables exist for Beat task tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def projects_beat_context() -> Iterator[sessionmaker]:
    """Reset Project rows and provide a sync session factory."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)

    def cleanup() -> None:
        """Delete Project rows in dependency order."""
        with session_factory() as session:
            session.execute(delete(AuditLog))
            session.execute(delete(WorkspaceMessage))
            session.execute(delete(ProposalAmendment))
            session.execute(delete(Project))
            session.execute(delete(Proposal))
            session.execute(delete(UserRole))
            session.execute(delete(User))
            session.commit()

    cleanup()
    try:
        yield session_factory
    finally:
        cleanup()
        sync_engine.dispose()


def create_project_with_pending_proposal(
    session_factory: sessionmaker,
    *,
    project_status: str,
    expires_at: datetime,
) -> tuple[UUID, UUID]:
    """Create a Project and one pending Proposal for Beat task assertions."""
    with session_factory() as session:
        operator = User(
            email=f"beat-operator-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Beat Operator",
            email_verified=True,
            kyc_status="verified",
        )
        contributor = User(
            email=f"beat-contributor-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Beat Contributor",
            email_verified=True,
            kyc_status="verified",
        )
        session.add_all([operator, contributor])
        session.flush()
        session.add_all(
            [
                UserRole(
                    user_id=operator.id,
                    role="operator",
                    approved_at=datetime.now(UTC),
                ),
                UserRole(
                    user_id=contributor.id,
                    role="contributor",
                    approved_at=datetime.now(UTC),
                ),
            ]
        )
        project = Project(
            operator_id=operator.id,
            title="Expired Project",
            description="Expired Project description.",
            category="operations",
            required_deliverables=[
                {"name": "Guide", "description": "Implementation guide"}
            ],
            budget_min=Decimal("100.00"),
            budget_max=Decimal("200.00"),
            currency="USD",
            status=project_status,
            expires_at=expires_at,
        )
        session.add(project)
        session.flush()
        proposal = Proposal(
            project_id=project.id,
            contributor_id=contributor.id,
            scope="I will complete the expired Project work.",
            budget=Decimal("150.00"),
            currency="USD",
            timeline_days=14,
            deliverables=[{"name": "Guide", "description": "Guide"}],
        )
        session.add(proposal)
        session.commit()
        return project.id, proposal.id


def create_expired_pending_amendment(session_factory: sessionmaker) -> UUID:
    """Create an accepted Proposal with an expired pending Amendment."""
    with session_factory() as session:
        project_id, proposal_id = create_project_with_pending_proposal(
            session_factory,
            project_status="assigned",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        proposal = session.get(Proposal, proposal_id)
        project = session.get(Project, project_id)
        assert proposal is not None
        assert project is not None
        proposal.status = "accepted"
        proposal.accepted_at = datetime.now(UTC)
        project.accepted_proposal_id = proposal.id
        amendment = ProposalAmendment(
            proposal_id=proposal.id,
            proposed_by=proposal.contributor_id,
            change_type="timeline",
            before={
                "scope": proposal.scope,
                "budget": f"{proposal.budget:.2f}",
                "timeline_days": proposal.timeline_days,
            },
            after={
                "scope": proposal.scope,
                "budget": f"{proposal.budget:.2f}",
                "timeline_days": proposal.timeline_days + 7,
            },
            reason="Need more calendar time.",
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        session.add(amendment)
        session.commit()
        return amendment.id


def test_close_expired_projects_closes_open_projects_and_withdraws_proposals(
    migrated_database: None,
    projects_beat_context: sessionmaker,
) -> None:
    """Expired open Projects close and their pending Proposals withdraw."""
    project_id, proposal_id = create_project_with_pending_proposal(
        projects_beat_context,
        project_status="open",
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )

    result = projects_beat.close_expired_projects.apply().get()

    with projects_beat_context() as session:
        project = session.get(Project, project_id)
        proposal = session.get(Proposal, proposal_id)

    assert result == {"closed_count": 1, "withdrawn_count": 1}
    assert project is not None
    assert project.status == "closed"
    assert project.closed_at is not None
    assert proposal is not None
    assert proposal.status == "withdrawn"
    assert proposal.withdrawn_at is not None


def test_expire_open_proposals_withdraws_pending_proposals_on_closed_projects(
    migrated_database: None,
    projects_beat_context: sessionmaker,
) -> None:
    """Pending Proposals on already closed Projects are withdrawn idempotently."""
    _, proposal_id = create_project_with_pending_proposal(
        projects_beat_context,
        project_status="closed",
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )

    result = projects_beat.expire_open_proposals.apply().get()
    second_result = projects_beat.expire_open_proposals.apply().get()

    with projects_beat_context() as session:
        proposal = session.get(Proposal, proposal_id)

    assert result == {"withdrawn_count": 1}
    assert second_result == {"withdrawn_count": 0}
    assert proposal is not None
    assert proposal.status == "withdrawn"


def test_expire_pending_amendments_marks_expired_and_writes_workspace_message(
    migrated_database: None,
    projects_beat_context: sessionmaker,
) -> None:
    """Expired pending Amendments are marked expired exactly once."""
    amendment_id = create_expired_pending_amendment(projects_beat_context)

    result = projects_beat.expire_pending_amendments.apply().get()
    second_result = projects_beat.expire_pending_amendments.apply().get()

    with projects_beat_context() as session:
        amendment = session.get(ProposalAmendment, amendment_id)
        messages = session.query(WorkspaceMessage).all()

    assert result == {"expired_count": 1}
    assert second_result == {"expired_count": 0}
    assert amendment is not None
    assert amendment.status == "expired"
    assert [message.system_event for message in messages] == ["amendment_expired"]
