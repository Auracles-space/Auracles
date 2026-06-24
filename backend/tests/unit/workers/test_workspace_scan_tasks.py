"""Tests for workspace attachment scan tasks."""

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
from app.modules.projects.models import Project, Proposal
from app.modules.workspace.models import WorkspaceMessage
from app.shared.models.audit_log import AuditLog
from app.workers.async_runner import run_async
from app.workers.tasks import workspace_scan


async def dispose_async_engine() -> None:
    """Close async DB transports before sync fixtures continue."""
    await engine.dispose()
    await asyncio.sleep(0.1)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure workspace tables exist for scan task tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def workspace_scan_context() -> Iterator[sessionmaker]:
    """Reset workspace rows and provide a sync session factory."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)

    def cleanup() -> None:
        """Delete rows in dependency order."""
        with session_factory() as session:
            session.execute(delete(AuditLog))
            session.execute(delete(WorkspaceMessage))
            session.execute(delete(Project))
            session.execute(delete(Proposal))
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


def create_pending_scan_message(session_factory: sessionmaker) -> UUID:
    """Create a pending-scan message attached to an accepted Project."""
    with session_factory() as session:
        operator = User(
            email=f"scan-operator-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Scan Operator",
            email_verified=True,
            kyc_status="verified",
        )
        contributor = User(
            email=f"scan-contributor-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Scan Contributor",
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
            title="Workspace Scan Project",
            description="Project used by workspace scan tests.",
            category="operations",
            required_deliverables=[
                {"name": "Guide", "description": "Implementation guide"}
            ],
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
            scope="I will complete the workspace scan work.",
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
        message = WorkspaceMessage(
            project_id=project.id,
            sender_id=contributor.id,
            body="Please scan this.",
            file_keys=["workspace/test/file.pdf"],
            scan_status="pending_scan",
        )
        session.add(message)
        session.commit()
        return message.id


def test_scan_workspace_upload_notifies_uploader_on_quarantine(
    migrated_database: None,
    workspace_scan_context: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An infected workspace attachment notifies its uploader of the quarantine."""
    from app.modules.projects import notifications as project_notifications

    message_id = create_pending_scan_message(workspace_scan_context)
    with workspace_scan_context() as session:
        message = session.get(WorkspaceMessage, message_id)
        assert message is not None
        uploader_id = message.sender_id

    calls: list[dict[str, object]] = []

    class _Recorder:
        """Capture notification dispatches without Celery or Redis."""

        def delay(self, **kwargs: object) -> None:
            calls.append(kwargs)

    def fake_download_file(bucket: str, key: str, destination: str) -> None:
        """Write scan input without contacting S3."""
        del bucket, key
        with open(destination, "wb") as local_file:
            local_file.write(b"infected")

    def fake_scan_file(path: str) -> str:
        """Return an infected scan result."""
        del path
        return "infected"

    async def fake_publish(
        channel: str,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        """Swallow realtime publishes in the quarantine path."""
        del channel, event_type, payload

    monkeypatch.setattr(workspace_scan.s3.storage, "download_file", fake_download_file)
    monkeypatch.setattr(workspace_scan, "scan_file_with_clamav", fake_scan_file)
    monkeypatch.setattr(workspace_scan, "publish_to_channel", fake_publish)
    monkeypatch.setattr(
        project_notifications,
        "dispatch_project_notification",
        _Recorder(),
    )

    result = workspace_scan.scan_workspace_upload.apply(args=[str(message_id)]).get()

    assert result == "quarantined"
    quarantine_calls = [
        call
        for call in calls
        if call["notification_type"] == "workspace_file_quarantined"
    ]
    assert len(quarantine_calls) == 1
    assert quarantine_calls[0]["user_id"] == str(uploader_id)


def test_scan_workspace_upload_marks_clean_message_visible(
    migrated_database: None,
    workspace_scan_context: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clean workspace attachments become visible and publish a realtime event."""
    message_id = create_pending_scan_message(workspace_scan_context)
    published: list[dict[str, object]] = []

    def fake_download_file(bucket: str, key: str, destination: str) -> None:
        """Write scan input without contacting S3."""
        del bucket, key
        with open(destination, "wb") as local_file:
            local_file.write(b"clean")

    def fake_scan_file(path: str) -> str:
        """Return a clean scan result."""
        del path
        return "clean"

    async def fake_publish(
        channel: str,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        """Record realtime publish calls."""
        published.append(
            {"channel": channel, "event_type": event_type, "payload": payload}
        )

    monkeypatch.setattr(workspace_scan.s3.storage, "download_file", fake_download_file)
    monkeypatch.setattr(workspace_scan, "scan_file_with_clamav", fake_scan_file)
    monkeypatch.setattr(workspace_scan, "publish_to_channel", fake_publish)

    result = workspace_scan.scan_workspace_upload.apply(args=[str(message_id)]).get()
    second_result = workspace_scan.scan_workspace_upload.apply(
        args=[str(message_id)]
    ).get()

    with workspace_scan_context() as session:
        message = session.get(WorkspaceMessage, message_id)

    assert result == "visible"
    assert second_result == "visible"
    assert message is not None
    assert message.scan_status == "visible"
    assert published == [
        {
            "channel": f"project:{message.project_id}",
            "event_type": "message_visible",
            "payload": {"message_id": str(message_id)},
        }
    ]
