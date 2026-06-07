"""Tests for Artifact extraction and PII processing pipeline tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID
from zipfile import ZipFile

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import engine
from app.core.security import hash_password
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework, FrameworkVersion, License, Review
from app.modules.frameworks.models_artifact import (
    Artifact,
    ArtifactDownload,
    ArtifactPiiAudit,
    ArtifactRarityAudit,
)
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import artifacts as artifact_tasks


class FakePipelineStorage:
    """S3 test double for pipeline download and redacted upload behavior."""

    def __init__(self) -> None:
        """Create empty upload history."""
        self.download_body: bytes | None = None
        self.uploads: dict[str, bytes] = {}

    def download_file(self, bucket: str, key: str, destination: str) -> None:
        """Write deterministic local input for extraction."""
        if self.download_body is not None:
            Path(destination).write_bytes(self.download_body)
            return
        Path(destination).write_text("local artifact placeholder", encoding="utf-8")

    def upload_bytes(
        self,
        bucket: str,
        key: str,
        body: bytes,
        mime_type: str,
    ) -> None:
        """Record a redacted object upload instead of touching S3."""
        self.uploads[key] = body


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure marketplace tables exist for pipeline tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def processing_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, Any]]:
    """Reset marketplace rows and install pipeline test doubles."""
    from app.workers.tasks.processing import extract

    fake_storage = FakePipelineStorage()
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    asyncio.run(engine.dispose())

    def cleanup() -> None:
        """Delete marketplace rows before users to satisfy foreign keys."""
        with session_factory() as session:
            session.execute(delete(AuditLog))
            session.execute(delete(Review))
            session.execute(delete(ArtifactDownload))
            session.execute(delete(License))
            session.execute(delete(ArtifactRarityAudit))
            session.execute(delete(ArtifactPiiAudit))
            session.execute(delete(FrameworkVersion))
            session.execute(delete(Artifact))
            session.execute(delete(Framework))
            session.execute(delete(UserRole))
            session.execute(delete(User))
            session.commit()

    cleanup()
    monkeypatch.setattr(artifact_tasks.s3, "storage", fake_storage)
    monkeypatch.setattr(extract.s3, "storage", fake_storage)
    try:
        yield {"storage": fake_storage}
    finally:
        cleanup()
        asyncio.run(engine.dispose())
        sync_engine.dispose()


def create_processing_artifact(
    *,
    name: str = "pipeline.pdf",
    mime_type: str = "application/pdf",
) -> UUID:
    """Create a clean Artifact ready for Slice 4 processing."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        user = User(
            email="pipeline-artifact@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="pipeline-artifact",
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
            title="Pipeline Framework",
            description="Pipeline Framework description",
            category="Operations",
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
            name=name,
            file_key=f"frameworks/{framework.id}/artifacts/{name}",
            file_size=256,
            mime_type=mime_type,
            scan_status="clean",
            processing_status="processing",
        )
        session.add(artifact)
        session.flush()
        artifact_id = artifact.id
        session.commit()
    sync_engine.dispose()
    return artifact_id


def build_docx_bytes(text: str) -> bytes:
    """Build a minimal DOCX-like Office XML zip for extraction tests."""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
                f"{text}"
                "</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
    return buffer.getvalue()


def build_zip_bytes(entries: dict[str, bytes]) -> bytes:
    """Build an in-memory ZIP file for extraction tests."""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def read_artifact_state(
    artifact_id: UUID,
) -> tuple[Artifact | None, ArtifactPiiAudit | None, AuditLog | None]:
    """Load the current Artifact, PII audit, and processing audit rows."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        artifact = session.get(Artifact, artifact_id)
        pii_audit = session.scalar(
            select(ArtifactPiiAudit).where(ArtifactPiiAudit.artifact_id == artifact_id)
        )
        audit_log = session.scalar(
            select(AuditLog).where(AuditLog.action == "artifact_pii_flagged")
        )
    sync_engine.dispose()
    return artifact, pii_audit, audit_log


def read_processing_failure(
    artifact_id: UUID,
) -> tuple[Artifact | None, AuditLog | None]:
    """Load an Artifact and its extraction failure audit row."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        artifact = session.get(Artifact, artifact_id)
        audit_log = session.scalar(
            select(AuditLog).where(
                AuditLog.action == "artifact_processing_failed",
                AuditLog.target_id == artifact_id,
            )
        )
    sync_engine.dispose()
    return artifact, audit_log


def test_process_artifact_flags_high_confidence_pii_for_review(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """High-confidence PII blocks processing until safe redaction is available."""
    from app.workers.tasks.processing import extract, pii

    artifact_id = create_processing_artifact()
    monkeypatch.setattr(
        extract,
        "extract_text_from_file",
        lambda *_: extract.ExtractionResult(
            text="Contact Ada Lovelace at ada@example.com.",
            headings=["Contacts"],
            table_count=1,
            word_count=6,
            image_count=0,
        ),
    )
    monkeypatch.setattr(
        pii,
        "detect_pii_from_text",
        lambda _: [
            pii.PiiFinding(entity_type="EMAIL_ADDRESS", score=0.97, start=23, end=38)
        ],
    )

    artifact_tasks.process_artifact.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, pii_audit, audit_log = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.metadata_vector is not None
    assert artifact.metadata_vector["extraction"]["word_count"] == 6
    assert artifact.pii_detected is True
    assert artifact.pii_review_needed is True
    assert artifact.clean_file_key is None
    assert processing_context["storage"].uploads == {}
    assert artifact.processing_status == "flagged_pii"
    assert pii_audit is not None
    assert pii_audit.pii_types_found == ["EMAIL_ADDRESS"]
    assert pii_audit.auto_redacted is False
    assert pii_audit.flagged_for_review is True
    assert audit_log is not None


def test_extract_text_can_rerun_without_duplicate_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Re-running extraction overwrites extraction metadata idempotently."""
    from app.workers.tasks.processing import extract

    artifact_id = create_processing_artifact()
    results = iter(
        [
            extract.ExtractionResult(
                text="First extraction.",
                headings=["First"],
                table_count=0,
                word_count=2,
                image_count=0,
            ),
            extract.ExtractionResult(
                text="Second extraction has more words.",
                headings=["Second"],
                table_count=2,
                word_count=5,
                image_count=1,
            ),
        ]
    )
    monkeypatch.setattr(extract, "extract_text_from_file", lambda *_: next(results))

    extract.extract_text.apply(args=[str(artifact_id)]).get()
    extract.extract_text.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, pii_audit, _ = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.metadata_vector is not None
    assert artifact.metadata_vector["extraction"]["text"] == (
        "Second extraction has more words."
    )
    assert artifact.metadata_vector["extraction"]["table_count"] == 2
    assert pii_audit is None


def test_extract_text_reads_supported_files_inside_zip(
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """ZIP Artifacts are containers whose supported inner files are extracted."""
    from app.workers.tasks.processing import extract

    storage = processing_context["storage"]
    storage.download_body = build_zip_bytes(
        {
            "framework/playbook.docx": build_docx_bytes(
                "Zip Operating Procedure Contact List"
            ),
            "framework/notes.txt": b"unsupported plain text",
        }
    )
    artifact_id = create_processing_artifact(
        name="framework-bundle.zip",
        mime_type="application/zip",
    )

    extract.extract_text.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, pii_audit, _ = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.metadata_vector is not None
    extraction = artifact.metadata_vector["extraction"]
    assert "Zip Operating Procedure Contact List" in extraction["text"]
    assert extraction["archive_file_count"] == 2
    assert extraction["archive_supported_file_count"] == 1
    assert extraction["archive_unsupported_file_count"] == 1
    assert pii_audit is None


def test_extract_text_rejects_zip_with_unsafe_path(
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """ZIP Artifacts with path traversal entries fail extraction safely."""
    from app.workers.tasks.processing import extract

    storage = processing_context["storage"]
    storage.download_body = build_zip_bytes(
        {"../evil.docx": build_docx_bytes("Should not be extracted")}
    )
    artifact_id = create_processing_artifact(
        name="unsafe.zip",
        mime_type="application/zip",
    )

    extract.extract_text.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, audit_log = read_processing_failure(artifact_id)

    assert artifact is not None
    assert artifact.processing_status == "failed"
    assert audit_log is not None
    assert audit_log.metadata_["step"] == "extract"


def test_process_artifact_flags_low_confidence_pii_for_review(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Low-confidence PII pauses the pipeline for Contributor review."""
    from app.workers.tasks.processing import extract, pii

    artifact_id = create_processing_artifact()
    monkeypatch.setattr(
        extract,
        "extract_text_from_file",
        lambda *_: extract.ExtractionResult(
            text="Possible phone number: 555-0100.",
            headings=[],
            table_count=0,
            word_count=4,
            image_count=0,
        ),
    )
    monkeypatch.setattr(
        pii,
        "detect_pii_from_text",
        lambda _: [
            pii.PiiFinding(entity_type="PHONE_NUMBER", score=0.45, start=23, end=31)
        ],
    )

    artifact_tasks.process_artifact.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, pii_audit, audit_log = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.pii_detected is False
    assert artifact.pii_review_needed is True
    assert artifact.clean_file_key is None
    assert artifact.processing_status == "flagged_pii"
    assert pii_audit is not None
    assert pii_audit.pii_types_found == ["PHONE_NUMBER"]
    assert pii_audit.auto_redacted is False
    assert pii_audit.flagged_for_review is True
    assert audit_log is not None


def test_process_artifact_marks_failed_when_extraction_fails(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Corrupt or unsupported files fail at extraction with an audit record."""
    from app.workers.tasks.processing import extract

    artifact_id = create_processing_artifact()

    def fail_extraction(*_: object) -> extract.ExtractionResult:
        """Simulate a parser failure from a corrupt source file."""
        raise ValueError("corrupt pdf")

    monkeypatch.setattr(extract, "extract_text_from_file", fail_extraction)

    artifact_tasks.process_artifact.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, audit_log = read_processing_failure(artifact_id)

    assert artifact is not None
    assert artifact.processing_status == "failed"
    assert audit_log is not None
    assert audit_log.metadata_["step"] == "extract"
