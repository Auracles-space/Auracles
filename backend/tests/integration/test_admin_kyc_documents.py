"""Integration tests for the admin KYC document review queue.

Under manual identity verification an admin reviews the documents a user
submitted before deciding. These tests cover listing them, fetching one behind a
presigned URL, and the decision cascading onto the documents it settles.

Maps to: FR-AUTH-009, FR-SET-011, BR-SET-003.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    encrypt_totp_secret,
    hash_password,
)
from app.main import app
from app.modules.admin import service as admin_service
from app.modules.auth.models import KycDocument, User, UserRole
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async


class FakeTotpRedis:
    """In-memory Redis double so admin TOTP verification is deterministic."""

    def __init__(self) -> None:
        """Create empty in-memory Redis-like state."""
        self.values: dict[str, str] = {}
        self.counters: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored string or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool:
        """Store a string value, optionally respecting NX semantics."""
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a string value with a TTL."""
        del seconds
        self.values[key] = value

    async def delete(self, key: str) -> int:
        """Remove a stored key."""
        return 1 if self.values.pop(key, None) is not None else 0

    async def incr(self, key: str) -> int:
        """Increment and return a counter."""
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        """Record an expiry (no-op for the in-memory double)."""
        return True

    async def ttl(self, key: str) -> int:
        """Return a positive TTL so the limiter never repairs the window."""
        return 3600


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure identity tables exist for endpoint tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def admin_kyc_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[list[str]]:
    """Reset identity state, stub Redis, and record presigned GET requests."""
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    signed_keys: list[str] = []

    def fake_presigned_get(
        bucket: str,
        key: str,
        expires_in: int,
        *,
        download_name: str | None = None,
    ) -> str:
        """Return a deterministic presigned GET URL and record the key."""
        del bucket, expires_in, download_name
        signed_keys.append(key)
        return f"https://downloads.example.test/{key}?signed=1"

    monkeypatch.setattr(admin_service.s3.storage, "presigned_get", fake_presigned_get)
    app.dependency_overrides[get_redis] = lambda: FakeTotpRedis()
    try:
        yield signed_keys
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def _create_admin_with_totp(email: str) -> tuple[UUID, str]:
    """Create a verified admin with TOTP enabled; return its id and secret."""
    secret = pyotp.random_base32()
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                totp_enabled=True,
                totp_secret=encrypt_totp_secret(secret),
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(user_id=user.id, role="admin", approved_at=datetime.now(UTC))
            )
        return user.id, secret


async def _create_applicant(
    email: str,
    *,
    scan_status: str = "clean",
    include_awaiting: bool = False,
) -> tuple[UUID, UUID]:
    """Create a pending Contributor with one submitted document.

    Returns the user id and the submitted document's id. When
    ``include_awaiting`` is set, a second reserved-but-never-uploaded row is
    added so tests can prove it stays out of the review queue.
    """
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status="pending",
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(
                    user_id=user.id,
                    role="contributor",
                    approved_at=datetime.now(UTC),
                )
            )
            document = KycDocument(
                user_id=user.id,
                doc_type="national_id",
                s3_key=f"kyc/{user.id}/{uuid4()}.pdf",
                mime_type="application/pdf",
                file_size=210_000,
                status="pending",
                scan_status=scan_status,
            )
            session.add(document)
            if include_awaiting:
                session.add(
                    KycDocument(
                        user_id=user.id,
                        doc_type="passport",
                        s3_key=f"kyc/{user.id}/{uuid4()}.pdf",
                        mime_type="application/pdf",
                        file_size=180_000,
                        status="pending",
                        scan_status="awaiting_upload",
                    )
                )
            await session.flush()
            return user.id, document.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_admin_lists_submitted_documents_only(
    client: AsyncClient,
    migrated_database: None,
    admin_kyc_context: list[str],
) -> None:
    """The review queue shows submitted documents and hides reservations.

    A row still ``awaiting_upload`` has no file behind it; showing it would put
    an unopenable entry in front of a reviewer.
    """
    user_id, document_id = await _create_applicant(
        "applicant@auracles.space", include_awaiting=True
    )
    admin_id, _ = await _create_admin_with_totp("doc-admin@auracles.space")

    response = await client.get(
        f"/v1/admin/users/{user_id}/kyc/documents",
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert response.status_code == 200
    documents = response.json()["documents"]
    assert [item["id"] for item in documents] == [str(document_id)]
    assert documents[0]["doc_type"] == "national_id"
    assert documents[0]["scan_status"] == "clean"


async def test_admin_document_list_requires_admin_role(
    client: AsyncClient,
    migrated_database: None,
    admin_kyc_context: list[str],
) -> None:
    """A non-admin cannot read another user's identity documents (403).

    Enforces BR-SET-003.
    """
    user_id, _ = await _create_applicant("private@auracles.space")
    intruder_id, _ = await _create_applicant("intruder@auracles.space")

    response = await client.get(
        f"/v1/admin/users/{user_id}/kyc/documents",
        headers=auth_headers(intruder_id, ["contributor"]),
    )

    assert response.status_code == 403


async def test_admin_download_returns_presigned_url_and_audits(
    client: AsyncClient,
    migrated_database: None,
    admin_kyc_context: list[str],
) -> None:
    """Downloading a document returns a presigned URL and writes an audit row.

    Reading someone's identity papers is a PII access; it must leave a trace of
    who looked and when.
    """
    user_id, document_id = await _create_applicant("download@auracles.space")
    admin_id, _ = await _create_admin_with_totp("doc-admin2@auracles.space")

    response = await client.get(
        f"/v1/admin/users/{user_id}/kyc/documents/{document_id}/download",
        headers=auth_headers(admin_id, ["admin"]),
    )

    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "kyc_document_viewed",
                AuditLog.actor_id == admin_id,
            )
        )

    assert response.status_code == 200
    assert response.json()["download_url"].startswith("https://downloads.example.test/")
    assert len(admin_kyc_context) == 1
    assert audit is not None


async def test_admin_download_refuses_unscanned_document(
    client: AsyncClient,
    migrated_database: None,
    admin_kyc_context: list[str],
) -> None:
    """A document that has not cleared the scanner is not downloadable (409).

    Without this an unscanned upload from any account could be opened by staff.
    """
    user_id, document_id = await _create_applicant(
        "unscanned@auracles.space", scan_status="pending_scan"
    )
    admin_id, _ = await _create_admin_with_totp("doc-admin3@auracles.space")

    response = await client.get(
        f"/v1/admin/users/{user_id}/kyc/documents/{document_id}/download",
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert response.status_code == 409
    assert admin_kyc_context == []


async def test_admin_download_refuses_quarantined_document(
    client: AsyncClient,
    migrated_database: None,
    admin_kyc_context: list[str],
) -> None:
    """An infected document is never handed to a reviewer (409)."""
    user_id, document_id = await _create_applicant(
        "infected@auracles.space", scan_status="quarantined"
    )
    admin_id, _ = await _create_admin_with_totp("doc-admin4@auracles.space")

    response = await client.get(
        f"/v1/admin/users/{user_id}/kyc/documents/{document_id}/download",
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert response.status_code == 409
    assert admin_kyc_context == []


async def test_admin_download_rejects_document_of_another_user(
    client: AsyncClient,
    migrated_database: None,
    admin_kyc_context: list[str],
) -> None:
    """A document id from a different user is not reachable via this path (404).

    Guards against an admin URL being edited into a cross-user read that the
    audit trail would then attribute to the wrong subject.
    """
    _, document_id = await _create_applicant("subject-a@auracles.space")
    other_user_id, _ = await _create_applicant("subject-b@auracles.space")
    admin_id, _ = await _create_admin_with_totp("doc-admin5@auracles.space")

    response = await client.get(
        f"/v1/admin/users/{other_user_id}/kyc/documents/{document_id}/download",
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert response.status_code == 404


async def test_review_decision_settles_submitted_documents(
    client: AsyncClient,
    migrated_database: None,
    admin_kyc_context: list[str],
) -> None:
    """Approving a user marks their pending documents verified with the reviewer.

    A decision that left every document ``pending`` would leave the queue
    unable to distinguish reviewed applicants from waiting ones.
    """
    user_id, document_id = await _create_applicant("decide@auracles.space")
    admin_id, admin_totp = await _create_admin_with_totp("doc-admin6@auracles.space")

    response = await client.patch(
        f"/v1/admin/users/{user_id}/kyc",
        json={
            "status": "verified",
            "notes": "NIN slip matches the account name.",
            "totp_code": pyotp.TOTP(admin_totp).now(),
        },
        headers=auth_headers(admin_id, ["admin"]),
    )

    async with async_session_factory() as session:
        document = await session.get(KycDocument, document_id)

    assert response.status_code == 200
    assert document is not None
    assert document.status == "verified"
    assert document.reviewed_by == admin_id
    assert document.reviewed_at is not None
    assert document.notes == "NIN slip matches the account name."


async def test_review_decision_emails_the_applicant(
    client: AsyncClient,
    migrated_database: None,
    admin_kyc_context: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verdict is queued for email, not left as an in-app notice only.

    Manual review is invisible from the applicant's side: they upload a
    document and get no signal that anyone looked at it. QA reported exactly
    this gap on staging.
    """
    queued: list[dict[str, object]] = []
    monkeypatch.setattr(
        admin_service.send_kyc_verdict_notification,
        "delay",
        lambda **kwargs: queued.append(kwargs),
    )
    user_id, _document_id = await _create_applicant("emailed@auracles.space")
    admin_id, admin_totp = await _create_admin_with_totp(
        "doc-admin9@auracles.space"
    )

    response = await client.patch(
        f"/v1/admin/users/{user_id}/kyc",
        json={
            "status": "verified",
            "notes": None,
            "totp_code": pyotp.TOTP(admin_totp).now(),
        },
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert response.status_code == 200
    assert queued == [{"user_id": str(user_id), "verified": True}]


async def test_rejection_settles_documents_as_rejected(
    client: AsyncClient,
    migrated_database: None,
    admin_kyc_context: list[str],
) -> None:
    """Rejecting a user marks their pending documents rejected."""
    user_id, document_id = await _create_applicant("reject@auracles.space")
    admin_id, admin_totp = await _create_admin_with_totp("doc-admin7@auracles.space")

    response = await client.patch(
        f"/v1/admin/users/{user_id}/kyc",
        json={
            "status": "rejected",
            "notes": "Document is not legible.",
            "totp_code": pyotp.TOTP(admin_totp).now(),
        },
        headers=auth_headers(admin_id, ["admin"]),
    )

    async with async_session_factory() as session:
        document = await session.get(KycDocument, document_id)

    assert response.status_code == 200
    assert document is not None and document.status == "rejected"


async def test_rejected_user_may_submit_again(
    client: AsyncClient,
    migrated_database: None,
    admin_kyc_context: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected applicant is not locked out — they can submit a new document.

    Rejection is a correctable outcome (an unreadable photo, a wrong document
    type); only ``verified`` closes submission.
    """
    from app.modules.settings import service as settings_service

    user_id, _ = await _create_applicant("retry@auracles.space")
    async with async_session_factory() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            assert user is not None
            user.kyc_status = "rejected"

    def fake_presigned_post(
        bucket: str,
        key: str,
        mime_type: str,
        max_size: int,
        expires_in: int,
    ) -> dict[str, Any]:
        """Return a deterministic presigned POST payload."""
        del bucket, max_size, expires_in
        return {
            "url": "https://uploads.example.test",
            "fields": {"key": key, "Content-Type": mime_type},
        }

    monkeypatch.setattr(
        settings_service.s3.storage, "presigned_post", fake_presigned_post
    )

    response = await client.post(
        "/v1/settings/kyc/documents",
        headers=auth_headers(user_id, ["contributor"]),
        json={
            "doc_type": "national_id",
            "filename": "nin-slip-clearer.jpg",
            "mime_type": "image/jpeg",
            "file_size": 320_000,
        },
    )

    assert response.status_code == 200
