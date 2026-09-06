"""Tests for the KYC document virus-scan task.

An administrator opens these files during manual review, so the scan is the only
thing standing between any registered account and putting a chosen file in front
of staff. The task must therefore fail closed.

Maps to: FR-AUTH-009.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import engine
from app.core.security import hash_password
from app.modules.auth.models import KycDocument, User, UserRole
from app.shared.models.audit_log import AuditLog
from app.workers.async_runner import run_async
from app.workers.tasks import kyc_document_scan


async def dispose_async_engine() -> None:
    """Close async DB transports before sync fixtures continue."""
    await engine.dispose()
    await asyncio.sleep(0.1)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure identity tables exist for scan task tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def kyc_scan_context() -> Iterator[sessionmaker]:
    """Reset identity rows and provide a sync session factory."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)

    def cleanup() -> None:
        """Delete rows in dependency order."""
        with session_factory() as session:
            session.execute(delete(AuditLog))
            session.execute(delete(KycDocument))
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


def create_pending_scan_document(session_factory: sessionmaker) -> UUID:
    """Create a confirmed, not-yet-scanned KYC document for a pending user."""
    with session_factory() as session:
        user = User(
            email=f"kycscan-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Scan Contributor",
            email_verified=True,
            kyc_status="pending",
        )
        session.add(user)
        session.flush()
        document = KycDocument(
            user_id=user.id,
            doc_type="national_id",
            s3_key=f"kyc/{user.id}/{uuid4()}.pdf",
            mime_type="application/pdf",
            file_size=120_000,
            status="pending",
            scan_status="pending_scan",
        )
        session.add(document)
        session.commit()
        return document.id


def _stub_download(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> None:
    """Replace the S3 download with a local write of `payload`."""

    def fake_download_file(bucket: str, key: str, destination: str) -> None:
        del bucket, key
        with open(destination, "wb") as local_file:
            local_file.write(payload)

    monkeypatch.setattr(
        kyc_document_scan.s3.storage, "download_file", fake_download_file
    )


def test_scan_kyc_document_marks_clean(
    migrated_database: None,
    kyc_scan_context: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean document becomes downloadable, and re-running changes nothing.

    Idempotency matters because Celery may redeliver the task; a second run must
    not re-scan a settled document.
    """
    document_id = create_pending_scan_document(kyc_scan_context)
    _stub_download(monkeypatch, b"clean")
    monkeypatch.setattr(
        kyc_document_scan, "scan_file_with_clamav", lambda path: "clean"
    )

    result = kyc_document_scan.scan_kyc_document.apply(args=[str(document_id)]).get()
    repeat = kyc_document_scan.scan_kyc_document.apply(args=[str(document_id)]).get()

    with kyc_scan_context() as session:
        document = session.get(KycDocument, document_id)
        audit = session.scalar(
            select(AuditLog).where(AuditLog.action == "kyc_document_scan_complete")
        )

    assert result == "clean"
    assert repeat == "clean"
    assert document is not None and document.scan_status == "clean"
    assert audit is not None


def test_scan_kyc_document_quarantines_infected(
    migrated_database: None,
    kyc_scan_context: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An infected identity document is quarantined and never reaches a reviewer."""
    document_id = create_pending_scan_document(kyc_scan_context)
    _stub_download(monkeypatch, b"infected")
    monkeypatch.setattr(
        kyc_document_scan, "scan_file_with_clamav", lambda path: "infected"
    )

    result = kyc_document_scan.scan_kyc_document.apply(args=[str(document_id)]).get()

    with kyc_scan_context() as session:
        document = session.get(KycDocument, document_id)
        audit = session.scalar(
            select(AuditLog).where(AuditLog.action == "kyc_document_quarantined")
        )

    assert result == "quarantined"
    assert document is not None and document.scan_status == "quarantined"
    assert audit is not None


def test_scan_kyc_document_handles_deleted_document(
    migrated_database: None,
    kyc_scan_context: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A document deleted before the task runs resolves without raising.

    GDPR erasure removes KYC rows, and an in-flight scan must not turn that into
    a permanently retrying task.
    """
    monkeypatch.setattr(
        kyc_document_scan, "scan_file_with_clamav", lambda path: "clean"
    )

    result = kyc_document_scan.scan_kyc_document.apply(args=[str(uuid4())]).get()

    assert result == "missing"
