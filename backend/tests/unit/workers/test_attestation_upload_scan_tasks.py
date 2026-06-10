"""Tests for Attestation and Credential evidence upload scanning."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import engine
from app.core.security import hash_password
from app.modules.attestation.models import AttestationUploadSession, Credential
from app.modules.auth.models import User, UserRole
from app.shared.models.audit_log import AuditLog
from app.workers.async_runner import run_async
from app.workers.tasks import attestation_upload_scan


async def dispose_async_engine() -> None:
    """Close async DB transports before sync fixtures continue."""
    await engine.dispose()
    await asyncio.sleep(0.1)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure attestation upload scan tables exist for task tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def upload_scan_context() -> Iterator[sessionmaker]:
    """Reset upload scan rows and provide a sync session factory."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)

    def cleanup() -> None:
        """Delete rows in dependency order."""
        with session_factory() as session:
            session.execute(delete(AttestationUploadSession))
            session.execute(delete(Credential))
            session.execute(delete(AuditLog))
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


def create_pending_credential_upload(session_factory: sessionmaker) -> UUID:
    """Create a pending Credential evidence upload session."""
    with session_factory() as session:
        user = User(
            email=f"attestation-upload-scan-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Evidence Scanner",
            email_verified=True,
        )
        session.add(user)
        session.flush()
        session.add(
            UserRole(
                user_id=user.id,
                role="operator",
                approved_at=datetime.now(UTC),
            )
        )
        credential = Credential(
            user_id=user.id,
            title="Evidence Credential",
            issuer="Auracles Test",
            issued_date=datetime.now(UTC).date(),
        )
        session.add(credential)
        session.flush()
        upload_session = AttestationUploadSession(
            credential_id=credential.id,
            user_id=user.id,
            purpose="credential_evidence",
            s3_key=f"credentials/{credential.id}/{user.id}/scan.pdf",
            content_type="application/pdf",
            size_limit=10 * 1024 * 1024,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            scan_status="pending_scan",
        )
        session.add(upload_session)
        session.commit()
        return upload_session.id


def test_scan_attestation_upload_marks_clean_session_clean(
    migrated_database: None,
    upload_scan_context: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clean evidence uploads become attachable after scanning."""
    del migrated_database
    upload_session_id = create_pending_credential_upload(upload_scan_context)

    def fake_download_file(bucket: str, key: str, destination: str) -> None:
        """Write scan input without contacting S3."""
        del bucket, key
        with open(destination, "wb") as local_file:
            local_file.write(b"clean")

    def fake_scan_file(path: str) -> str:
        """Return a clean scan result."""
        del path
        return "clean"

    monkeypatch.setattr(
        attestation_upload_scan.s3.storage,
        "download_file",
        fake_download_file,
    )
    monkeypatch.setattr(
        attestation_upload_scan,
        "scan_file_with_clamav",
        fake_scan_file,
    )

    result = attestation_upload_scan.scan_attestation_upload.apply(
        args=[str(upload_session_id)]
    ).get()
    second_result = attestation_upload_scan.scan_attestation_upload.apply(
        args=[str(upload_session_id)]
    ).get()

    with upload_scan_context() as session:
        upload_session = session.get(AttestationUploadSession, upload_session_id)
        audit_action = session.scalar(select(AuditLog.action))

    assert result == "clean"
    assert second_result == "clean"
    assert upload_session is not None
    assert upload_session.scan_status == "clean"
    assert audit_action == "attestation_upload_scan_complete"


def test_scan_attestation_upload_quarantines_infected_session(
    migrated_database: None,
    upload_scan_context: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Infected evidence uploads are blocked from later report attachment."""
    del migrated_database
    upload_session_id = create_pending_credential_upload(upload_scan_context)

    def fake_download_file(bucket: str, key: str, destination: str) -> None:
        """Write scan input without contacting S3."""
        del bucket, key
        with open(destination, "wb") as local_file:
            local_file.write(b"infected")

    def fake_scan_file(path: str) -> str:
        """Return an infected scan result."""
        del path
        return "infected"

    monkeypatch.setattr(
        attestation_upload_scan.s3.storage,
        "download_file",
        fake_download_file,
    )
    monkeypatch.setattr(
        attestation_upload_scan,
        "scan_file_with_clamav",
        fake_scan_file,
    )

    result = attestation_upload_scan.scan_attestation_upload.apply(
        args=[str(upload_session_id)]
    ).get()

    with upload_scan_context() as session:
        upload_session = session.get(AttestationUploadSession, upload_session_id)
        audit_action = session.scalar(select(AuditLog.action))

    assert result == "infected"
    assert upload_session is not None
    assert upload_session.scan_status == "infected"
    assert audit_action == "attestation_upload_quarantined"
