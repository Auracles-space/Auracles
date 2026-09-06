"""Integration tests for manual KYC document submission.

Covers the contributor-facing half of manual identity verification: request a
presigned upload target, confirm the upload, and have the account move to
``pending`` so it lands in the admin review queue.

The provider path (Persona) is feature-flagged off in these tests, which is the
deployed configuration — ``KYC_PROVIDER=manual``.

Maps to: FR-AUTH-009, FR-SET-004.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import KycDocument, User, UserRole
from app.modules.settings import service as settings_service
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async


class FakeRateLimitRedis:
    """In-memory Redis double supporting the rate limiter's commands."""

    def __init__(self) -> None:
        """Create empty counter state."""
        self.counters: dict[str, int] = {}

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


class FakeScanTask:
    """Records `scan_kyc_document.delay` calls instead of enqueuing them."""

    def __init__(self, sink: list[str]) -> None:
        """Store the list that receives dispatched document ids."""
        self.sink = sink

    def delay(self, document_id: str) -> None:
        """Record a dispatched scan."""
        self.sink.append(document_id)


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
async def upload_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset identity state and stub Redis, S3 and the scan task.

    Yields the mutable recorders the tests assert on: dispatched scan ids and
    the set of object keys S3 is pretending to hold.
    """
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()

    dispatched: list[str] = []
    stored_keys: set[str] = set()

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

    def fake_object_exists(bucket: str, key: str) -> bool:
        """Report whether the test has marked this key as uploaded."""
        del bucket
        return key in stored_keys

    monkeypatch.setattr(
        settings_service.s3.storage, "presigned_post", fake_presigned_post
    )
    monkeypatch.setattr(
        settings_service.s3.storage, "object_exists", fake_object_exists
    )
    monkeypatch.setattr(
        settings_service, "scan_kyc_document", FakeScanTask(dispatched)
    )
    app.dependency_overrides[get_redis] = lambda: FakeRateLimitRedis()
    try:
        yield {"dispatched": dispatched, "stored_keys": stored_keys}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def _create_user(email: str, kyc_status: str = "unverified") -> UUID:
    """Create a verified Contributor with the given KYC status."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status=kyc_status,
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
        return user.id


def _auth_headers(user_id: UUID) -> dict[str, str]:
    """Create bearer auth headers for a test Contributor."""
    token = create_access_token(user_id=user_id, roles=["contributor"])
    return {"Authorization": f"Bearer {token}"}


def _upload_body(**overrides: Any) -> dict[str, Any]:
    """Build a valid upload request body, with overrides applied."""
    body: dict[str, Any] = {
        "doc_type": "national_id",
        "filename": "nin-slip.pdf",
        "mime_type": "application/pdf",
        "file_size": 240_000,
    }
    body.update(overrides)
    return body


async def test_request_upload_url_creates_awaiting_document(
    client: AsyncClient,
    migrated_database: None,
    upload_context: dict[str, Any],
) -> None:
    """Requesting an upload target returns a POST policy and reserves a row.

    The row is not yet part of the user's submitted set — it exists only so the
    object key is known before the browser uploads. Until the upload is
    confirmed it must not appear in the user's document list, and the account
    must not move to ``pending``.

    Enforces FR-AUTH-009.
    """
    user_id = await _create_user("upload@auracles.space")

    response = await client.post(
        "/v1/settings/kyc/documents",
        headers=_auth_headers(user_id),
        json=_upload_body(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["upload_url"] == "https://uploads.example.test"
    assert payload["fields"]["Content-Type"] == "application/pdf"
    assert payload["fields"]["key"].startswith(f"kyc/{user_id}/")
    assert payload["fields"]["key"].endswith(".pdf")

    async with async_session_factory() as session:
        document = await session.get(KycDocument, UUID(payload["document_id"]))
        user = await session.get(User, user_id)
    assert document is not None
    assert document.scan_status == "awaiting_upload"
    assert document.status == "pending"
    assert user is not None and user.kyc_status == "unverified"

    listed = await client.get("/v1/settings/kyc", headers=_auth_headers(user_id))
    assert listed.json()["documents"] == []


async def test_request_upload_url_rejects_unsupported_mime(
    client: AsyncClient,
    migrated_database: None,
    upload_context: dict[str, Any],
) -> None:
    """An identity document in an unsupported format is refused with 415."""
    user_id = await _create_user("badmime@auracles.space")

    response = await client.post(
        "/v1/settings/kyc/documents",
        headers=_auth_headers(user_id),
        json=_upload_body(mime_type="application/zip", filename="id.zip"),
    )

    assert response.status_code == 415


async def test_request_upload_url_rejects_oversized_file(
    client: AsyncClient,
    migrated_database: None,
    upload_context: dict[str, Any],
) -> None:
    """A document larger than the KYC cap is refused with 413 before S3."""
    user_id = await _create_user("toobig@auracles.space")

    response = await client.post(
        "/v1/settings/kyc/documents",
        headers=_auth_headers(user_id),
        json=_upload_body(file_size=settings_service.KYC_DOCUMENT_MAX_SIZE + 1),
    )

    assert response.status_code == 413


async def test_request_upload_url_requires_authentication(
    client: AsyncClient,
    migrated_database: None,
    upload_context: dict[str, Any],
) -> None:
    """An unauthenticated upload request is rejected with 401."""
    response = await client.post("/v1/settings/kyc/documents", json=_upload_body())

    assert response.status_code == 401


async def test_request_upload_url_conflicts_when_already_verified(
    client: AsyncClient,
    migrated_database: None,
    upload_context: dict[str, Any],
) -> None:
    """A verified account cannot submit further documents (409).

    Re-submission would silently reopen a settled verification.
    """
    user_id = await _create_user("done@auracles.space", kyc_status="verified")

    response = await client.post(
        "/v1/settings/kyc/documents",
        headers=_auth_headers(user_id),
        json=_upload_body(),
    )

    assert response.status_code == 409


async def test_request_upload_url_caps_document_count(
    client: AsyncClient,
    migrated_database: None,
    upload_context: dict[str, Any],
) -> None:
    """Beyond the per-user document cap further requests are refused with 422.

    Bounds how much storage one account can reserve through this endpoint.
    """
    user_id = await _create_user("many@auracles.space")
    headers = _auth_headers(user_id)

    for _ in range(settings_service.KYC_MAX_DOCUMENTS):
        allowed = await client.post(
            "/v1/settings/kyc/documents", headers=headers, json=_upload_body()
        )
        assert allowed.status_code == 200

    refused = await client.post(
        "/v1/settings/kyc/documents", headers=headers, json=_upload_body()
    )

    assert refused.status_code == 422


async def _request_upload(client: AsyncClient, user_id: UUID) -> dict[str, Any]:
    """Request an upload target and return the response payload."""
    response = await client.post(
        "/v1/settings/kyc/documents",
        headers=_auth_headers(user_id),
        json=_upload_body(),
    )
    assert response.status_code == 200
    return dict(response.json())


async def test_confirm_marks_pending_and_dispatches_scan(
    client: AsyncClient,
    migrated_database: None,
    upload_context: dict[str, Any],
) -> None:
    """Confirming an uploaded document queues a scan and opens the review.

    The account moves to ``pending``, which is what places it in the admin
    ``kyc_pending`` queue, and the document becomes visible to its owner.

    Enforces FR-AUTH-009, FR-SET-004.
    """
    user_id = await _create_user("confirm@auracles.space")
    payload = await _request_upload(client, user_id)
    upload_context["stored_keys"].add(payload["fields"]["key"])

    response = await client.post(
        f"/v1/settings/kyc/documents/{payload['document_id']}/confirm",
        headers=_auth_headers(user_id),
    )

    assert response.status_code == 200
    assert response.json()["scan_status"] == "pending_scan"
    assert upload_context["dispatched"] == [payload["document_id"]]

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "kyc_document_uploaded")
        )
    assert user is not None and user.kyc_status == "pending"
    assert audit is not None

    listed = await client.get("/v1/settings/kyc", headers=_auth_headers(user_id))
    documents = listed.json()["documents"]
    assert len(documents) == 1
    assert documents[0]["doc_type"] == "national_id"


async def test_confirm_rejects_document_never_uploaded(
    client: AsyncClient,
    migrated_database: None,
    upload_context: dict[str, Any],
) -> None:
    """Confirming without an object in storage is refused with 422.

    Without this check a user could open a review with no document behind it.
    """
    user_id = await _create_user("nofile@auracles.space")
    payload = await _request_upload(client, user_id)

    response = await client.post(
        f"/v1/settings/kyc/documents/{payload['document_id']}/confirm",
        headers=_auth_headers(user_id),
    )

    assert response.status_code == 422
    assert upload_context["dispatched"] == []


async def test_confirm_rejects_another_users_document(
    client: AsyncClient,
    migrated_database: None,
    upload_context: dict[str, Any],
) -> None:
    """A document belonging to another account is not confirmable (404).

    Guards against an IDOR that would attach a stranger's upload to the
    caller's verification.
    """
    owner_id = await _create_user("owner@auracles.space")
    attacker_id = await _create_user("attacker@auracles.space")
    payload = await _request_upload(client, owner_id)
    upload_context["stored_keys"].add(payload["fields"]["key"])

    response = await client.post(
        f"/v1/settings/kyc/documents/{payload['document_id']}/confirm",
        headers=_auth_headers(attacker_id),
    )

    assert response.status_code == 404
    assert upload_context["dispatched"] == []


async def test_confirm_is_idempotent(
    client: AsyncClient,
    migrated_database: None,
    upload_context: dict[str, Any],
) -> None:
    """A repeated confirm returns the document without re-queuing the scan."""
    user_id = await _create_user("twice@auracles.space")
    payload = await _request_upload(client, user_id)
    upload_context["stored_keys"].add(payload["fields"]["key"])
    headers = _auth_headers(user_id)
    confirm_url = f"/v1/settings/kyc/documents/{payload['document_id']}/confirm"

    first = await client.post(confirm_url, headers=headers)
    second = await client.post(confirm_url, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert upload_context["dispatched"] == [payload["document_id"]]


async def test_confirm_unknown_document_is_not_found(
    client: AsyncClient,
    migrated_database: None,
    upload_context: dict[str, Any],
) -> None:
    """Confirming an id that does not exist returns 404."""
    user_id = await _create_user("ghost@auracles.space")

    response = await client.post(
        f"/v1/settings/kyc/documents/{uuid4()}/confirm",
        headers=_auth_headers(user_id),
    )

    assert response.status_code == 404


async def test_document_list_never_exposes_the_storage_key(
    client: AsyncClient,
    migrated_database: None,
    upload_context: dict[str, Any],
) -> None:
    """The owner's document list must not leak the S3 object key.

    Files are delivered by presigned URL only; publishing the key gives an
    attacker who later obtains credentials a ready-made target list.
    """
    user_id = await _create_user("nokey@auracles.space")
    payload = await _request_upload(client, user_id)
    upload_context["stored_keys"].add(payload["fields"]["key"])
    await client.post(
        f"/v1/settings/kyc/documents/{payload['document_id']}/confirm",
        headers=_auth_headers(user_id),
    )

    listed = await client.get("/v1/settings/kyc", headers=_auth_headers(user_id))

    assert "s3_key" not in listed.json()["documents"][0]


async def test_provider_session_is_disabled_under_manual_kyc(
    client: AsyncClient,
    migrated_database: None,
    upload_context: dict[str, Any],
) -> None:
    """With KYC_PROVIDER=manual the Persona session endpoint is not available.

    The provider flow stays in the codebase behind the flag; leaving it
    reachable would hand users a link that dead-ends at an inactive account.
    """
    user_id = await _create_user("noprovider@auracles.space")

    response = await client.post(
        "/v1/settings/kyc/session", headers=_auth_headers(user_id)
    )

    assert response.status_code == 404
