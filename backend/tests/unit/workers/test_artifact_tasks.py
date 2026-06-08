"""Tests for Artifact Celery task state transitions."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import engine
from app.core.security import hash_password
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import (
    Framework,
    FrameworkVersion,
    FrameworkVersionArtifact,
    License,
    Review,
)
from app.modules.frameworks.models_artifact import (
    Artifact,
    ArtifactDownload,
    ArtifactPiiAudit,
    ArtifactRarityAudit,
)
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import artifacts as artifact_tasks


class FakeArtifactStorage:
    """S3 test double that writes a fake object to the requested path."""

    def download_file(self, bucket: str, key: str, destination: str) -> None:
        """Write deterministic scan input bytes."""
        Path(destination).write_bytes(b"fake artifact")


class FakeProcessTask:
    """Celery task double for the post-scan processing orchestrator."""

    def __init__(self) -> None:
        """Create empty dispatch history."""
        self.dispatched: list[str] = []

    def delay(self, artifact_id: str) -> None:
        """Record dispatch instead of touching Celery/Redis."""
        self.dispatched.append(artifact_id)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure marketplace tables exist for worker tests."""
    settings = get_settings()
    sync_engine = create_engine(
        settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def artifact_task_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, Any]]:
    """Reset marketplace rows and install task test doubles."""
    fake_process = FakeProcessTask()
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)

    def cleanup() -> None:
        """Delete marketplace rows before users to satisfy foreign keys."""
        with session_factory() as session:
            session.execute(delete(AuditLog))
            session.execute(delete(Review))
            session.execute(delete(ArtifactDownload))
            session.execute(delete(License))
            session.execute(delete(ArtifactRarityAudit))
            session.execute(delete(ArtifactPiiAudit))
            session.execute(delete(FrameworkVersionArtifact))
            session.execute(delete(FrameworkVersion))
            session.execute(delete(Artifact))
            session.execute(delete(Framework))
            session.execute(delete(UserRole))
            session.execute(delete(User))
            session.commit()

    cleanup()
    monkeypatch.setattr(artifact_tasks.s3, "storage", FakeArtifactStorage())
    monkeypatch.setattr(artifact_tasks, "process_artifact", fake_process)
    try:
        yield {"process_task": fake_process}
    finally:
        cleanup()
        sync_engine.dispose()


def create_pending_artifact() -> UUID:
    """Create a Framework and pending Artifact for task tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        user = User(
            email="task-artifact@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="task-artifact",
            email_verified=True,
            kyc_status="verified",
        )
        session.add(user)
        session.flush()
        session.add(
            UserRole(
                user_id=user.id,
                role="contributor",
                approved_at=datetime.now(UTC),
            )
        )
        framework = Framework(
            contributor_id=user.id,
            title="Task Framework",
            description="Task Framework description",
            category="toolkit",
            tags=[],
            tags_text="",
            price="100.00",
            currency="USD",
            license_types=["single_user"],
        )
        session.add(framework)
        session.flush()
        artifact = Artifact(
            framework_id=framework.id,
            name="task.pdf",
            file_key=f"frameworks/{framework.id}/artifacts/task.pdf",
            file_size=256,
            mime_type="application/pdf",
            processing_status="processing",
        )
        session.add(artifact)
        session.flush()
        artifact_id = artifact.id
        session.commit()
    sync_engine.dispose()
    return artifact_id


def test_scan_artifact_marks_clean_and_dispatches_processing(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    artifact_task_context: dict[str, Any],
) -> None:
    """Clean ClamAV result advances the Artifact to downstream processing."""
    artifact_id = create_pending_artifact()
    monkeypatch.setattr(artifact_tasks, "scan_file_with_clamav", lambda _: "clean")

    artifact_tasks.scan_artifact.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    def read_result() -> tuple[Artifact | None, AuditLog | None]:
        """Load the task result rows."""
        settings = get_settings()
        sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
        session_factory = sessionmaker(sync_engine)
        with session_factory() as session:
            artifact = session.get(Artifact, artifact_id)
            audit_log = session.scalar(
                select(AuditLog).where(AuditLog.action == "artifact_scan_complete")
            )
            return artifact, audit_log

    artifact, audit_log = read_result()

    assert artifact is not None
    assert artifact.scan_status == "clean"
    assert artifact.processing_status == "processing"
    assert artifact_task_context["process_task"].dispatched == [str(artifact_id)]
    assert audit_log is not None


def test_scan_artifact_marks_infected_and_stops_processing(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    artifact_task_context: dict[str, Any],
) -> None:
    """Infected ClamAV result fails the Artifact and skips processing."""
    artifact_id = create_pending_artifact()
    monkeypatch.setattr(artifact_tasks, "scan_file_with_clamav", lambda _: "infected")

    artifact_tasks.scan_artifact.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    def read_result() -> tuple[Artifact | None, AuditLog | None]:
        """Load the task result rows."""
        settings = get_settings()
        sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
        session_factory = sessionmaker(sync_engine)
        with session_factory() as session:
            artifact = session.get(Artifact, artifact_id)
            audit_log = session.scalar(
                select(AuditLog).where(AuditLog.action == "virus_detected")
            )
            return artifact, audit_log

    artifact, audit_log = read_result()

    assert artifact is not None
    assert artifact.scan_status == "infected"
    assert artifact.processing_status == "failed"
    assert artifact_task_context["process_task"].dispatched == []
    assert audit_log is not None


def test_scan_artifact_error_state_matches_retry_exhaustion_policy(
    migrated_database: None,
    artifact_task_context: dict[str, Any],
) -> None:
    """ClamAV retry exhaustion records the expected Artifact error state."""
    artifact_id = create_pending_artifact()
    assert artifact_tasks.scan_artifact.max_retries == 5

    asyncio.run(
        artifact_tasks._set_scan_result(
            artifact_id,
            scan_status="error",
            processing_status="failed",
            audit_action="artifact_processing_failed",
        )
    )
    asyncio.run(engine.dispose())

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        artifact = session.get(Artifact, artifact_id)
        audit_log = session.scalar(
            select(AuditLog).where(AuditLog.action == "artifact_processing_failed")
        )

    assert artifact is not None
    assert artifact.scan_status == "error"
    assert artifact.processing_status == "failed"
    assert artifact_task_context["process_task"].dispatched == []
    assert audit_log is not None
