"""Tests for Deliverable evidence virus-scan tasks."""

from __future__ import annotations

import asyncio
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
from app.core.database import engine
from app.core.security import hash_password
from app.modules.auth.models import User, UserRole
from app.modules.projects.models import (
    Deliverable,
    Milestone,
    Project,
    Proposal,
)
from app.shared.models.audit_log import AuditLog
from app.workers.async_runner import run_async
from app.workers.tasks import deliverable_scan


async def dispose_async_engine() -> None:
    """Close async DB transports before sync fixtures continue."""
    await engine.dispose()
    await asyncio.sleep(0.1)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure project tables exist for scan task tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def deliverable_scan_context() -> Iterator[sessionmaker]:
    """Reset project rows and provide a sync session factory."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)

    def cleanup() -> None:
        """Delete rows in dependency order."""
        with session_factory() as session:
            session.execute(delete(AuditLog))
            session.execute(delete(Deliverable))
            session.execute(delete(Milestone))
            session.execute(delete(Proposal))
            session.execute(delete(Project))
            session.execute(delete(UserRole))
            session.execute(delete(User))
            session.commit()

    cleanup()
    try:
        yield session_factory
    finally:
        run_async(dispose_async_engine())
        cleanup()
        sync_engine.dispose()


def create_pending_scan_deliverable(session_factory: sessionmaker) -> UUID:
    """Create a pending-scan Deliverable under an accepted Project Milestone."""
    with session_factory() as session:
        operator = User(
            email=f"dscan-operator-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Scan Operator",
            email_verified=True,
            kyc_status="verified",
        )
        contributor = User(
            email=f"dscan-contributor-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Scan Contributor",
            email_verified=True,
            kyc_status="verified",
        )
        session.add_all([operator, contributor])
        session.flush()
        project = Project(
            operator_id=operator.id,
            title="Deliverable Scan Project",
            description="Project used by deliverable scan tests.",
            category="operations",
            required_deliverables=[{"name": "Guide", "description": "Guide"}],
            budget_min=Decimal("150.00"),
            budget_max=Decimal("150.00"),
            currency="USD",
            status="assigned",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        session.add(project)
        session.flush()
        proposal = Proposal(
            project_id=project.id,
            contributor_id=contributor.id,
            scope="I will complete the deliverable scan work.",
            budget=Decimal("150.00"),
            currency="USD",
            timeline_days=14,
            deliverables=[{"name": "Guide", "description": "Guide"}],
            status="accepted",
            accepted_at=datetime.now(UTC),
        )
        session.add(proposal)
        session.flush()
        project.accepted_proposal_id = proposal.id
        milestone = Milestone(
            project_id=project.id,
            sequence=1,
            name="Implementation",
            description="Build the work.",
            budget=Decimal("150.00"),
            currency="USD",
        )
        session.add(milestone)
        session.flush()
        deliverable = Deliverable(
            milestone_id=milestone.id,
            contributor_id=contributor.id,
            name="Final playbook",
            description="Implementation playbook.",
            file_keys=["workspace/test/deliverable.pdf"],
            status="submitted",
            scan_status="pending_scan",
        )
        session.add(deliverable)
        session.commit()
        return deliverable.id


def test_scan_deliverable_marks_clean_visible(
    migrated_database: None,
    deliverable_scan_context: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean Deliverable scan flips scan_status to visible (idempotently)."""
    deliverable_id = create_pending_scan_deliverable(deliverable_scan_context)

    def fake_download_file(bucket: str, key: str, destination: str) -> None:
        del bucket, key
        with open(destination, "wb") as local_file:
            local_file.write(b"clean")

    monkeypatch.setattr(
        deliverable_scan.s3.storage, "download_file", fake_download_file
    )
    monkeypatch.setattr(deliverable_scan, "scan_file_with_clamav", lambda path: "clean")

    result = deliverable_scan.scan_deliverable_upload.apply(
        args=[str(deliverable_id)]
    ).get()
    repeat = deliverable_scan.scan_deliverable_upload.apply(
        args=[str(deliverable_id)]
    ).get()

    with deliverable_scan_context() as session:
        deliverable = session.get(Deliverable, deliverable_id)

    assert result == "visible"
    assert repeat == "visible"
    assert deliverable is not None
    assert deliverable.scan_status == "visible"


def test_scan_deliverable_quarantines_infected(
    migrated_database: None,
    deliverable_scan_context: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An infected Deliverable file flips scan_status to quarantined."""
    deliverable_id = create_pending_scan_deliverable(deliverable_scan_context)

    def fake_download_file(bucket: str, key: str, destination: str) -> None:
        del bucket, key
        with open(destination, "wb") as local_file:
            local_file.write(b"infected")

    monkeypatch.setattr(
        deliverable_scan.s3.storage, "download_file", fake_download_file
    )
    monkeypatch.setattr(
        deliverable_scan, "scan_file_with_clamav", lambda path: "infected"
    )

    result = deliverable_scan.scan_deliverable_upload.apply(
        args=[str(deliverable_id)]
    ).get()

    with deliverable_scan_context() as session:
        deliverable = session.get(Deliverable, deliverable_id)

    assert result == "quarantined"
    assert deliverable is not None
    assert deliverable.scan_status == "quarantined"
