"""Integration tests for Phase 5c Slice 3 GDPR data export requests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.gdpr import export_service as gdpr_export_service
from app.modules.gdpr.models import DataExportRequest
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import gdpr_beat


class FakeRedis:
    """Redis test double for GDPR export request rate limiting."""

    def __init__(self) -> None:
        """Create empty counter state."""
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        """Increment and return a counter."""
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """Record a TTL for a key."""
        self.ttls[key] = seconds

    async def ttl(self, key: str) -> int:
        """Return a recorded TTL or Redis' no-expiry sentinel."""
        return self.ttls.get(key, -1)


class QueuedTasks:
    """Capture Celery task dispatches from request endpoints."""

    def __init__(self) -> None:
        """Create empty dispatch storage."""
        self.export_request_ids: list[str] = []

    def generate_data_export_delay(self, request_id: str) -> None:
        """Record a GDPR export task dispatch."""
        self.export_request_ids.append(request_id)


class FakeS3Storage:
    """S3 test double that captures uploaded export bytes."""

    def __init__(self) -> None:
        """Create empty upload storage."""
        self.uploads: list[dict[str, Any]] = []
        self.presigned_get_requests: list[dict[str, Any]] = []
        self.deleted_objects: list[tuple[str, str]] = []

    def upload_bytes(
        self,
        bucket: str,
        key: str,
        body: bytes,
        mime_type: str,
    ) -> None:
        """Capture one private object upload."""
        self.uploads.append(
            {
                "bucket": bucket,
                "key": key,
                "body": body,
                "mime_type": mime_type,
            }
        )

    def presigned_get(
        self,
        bucket: str,
        key: str,
        expires_in: int,
        *,
        download_name: str | None = None,
    ) -> str:
        """Return a deterministic fake presigned GET URL."""
        self.presigned_get_requests.append(
            {
                "bucket": bucket,
                "key": key,
                "expires_in": expires_in,
                "download_name": download_name,
            }
        )
        return (
            f"https://s3.test/{bucket}/{key}"
            f"?expires={expires_in}&download_name={download_name}"
        )

    def delete_object(self, bucket: str, key: str) -> None:
        """Record a private object deletion request."""
        self.deleted_objects.append((bucket, key))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure GDPR export tables exist."""
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
async def export_test_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset auth/export state and install Redis/Celery test doubles."""
    fake_redis = FakeRedis()
    queued_tasks = QueuedTasks()
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(DataExportRequest))
        await session.execute(delete(AuditLog))
        await session.commit()

    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr(
        gdpr_beat.generate_data_export,
        "delay",
        queued_tasks.generate_data_export_delay,
    )
    try:
        yield {"redis": fake_redis, "queued_tasks": queued_tasks}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await engine.dispose()


async def create_verified_user(email: str) -> UUID:
    """Create a verified Operator user for GDPR export tests."""
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
            session.add(
                UserRole(
                    user_id=user.id,
                    role="operator",
                    approved_at=datetime.now(UTC),
                )
            )
        return user.id


def auth_headers(user_id: UUID) -> dict[str, str]:
    """Create bearer auth headers for a GDPR export test user."""
    return {"Authorization": f"Bearer {create_access_token(user_id, ['operator'])}"}


async def test_user_requests_export_and_duplicate_active_request_is_rejected(
    client: AsyncClient,
    migrated_database: None,
    export_test_context: dict[str, Any],
) -> None:
    """A user can request one active export and receives a status resource."""
    del migrated_database
    user_id = await create_verified_user("export-owner@auracles.space")

    created = await client.post(
        "/v1/gdpr/exports",
        headers=auth_headers(user_id),
    )
    duplicate = await client.post(
        "/v1/gdpr/exports",
        headers=auth_headers(user_id),
    )
    export_id = created.json()["id"]
    status_response = await client.get(
        f"/v1/gdpr/exports/{export_id}",
        headers=auth_headers(user_id),
    )

    async with async_session_factory() as session:
        request = await session.get(DataExportRequest, UUID(export_id))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "gdpr_export_requested")
        )

    assert created.status_code == 202
    assert created.json()["status"] == "pending"
    assert duplicate.status_code == 409
    assert status_response.status_code == 200
    assert status_response.json()["id"] == export_id
    assert status_response.json()["status"] == "pending"
    assert request is not None
    assert request.user_id == user_id
    assert audit is not None
    assert export_test_context["queued_tasks"].export_request_ids == [export_id]


async def test_export_status_is_owner_checked(
    client: AsyncClient,
    migrated_database: None,
    export_test_context: dict[str, Any],
) -> None:
    """Users cannot inspect another user's export request status."""
    del migrated_database, export_test_context
    owner_id = await create_verified_user("export-owner-2@auracles.space")
    other_id = await create_verified_user("export-other@auracles.space")
    created = await client.post(
        "/v1/gdpr/exports",
        headers=auth_headers(owner_id),
    )

    response = await client.get(
        f"/v1/gdpr/exports/{created.json()['id']}",
        headers=auth_headers(other_id),
    )

    assert response.status_code == 404


async def test_user_can_load_the_latest_export_status_resource(
    client: AsyncClient,
    migrated_database: None,
    export_test_context: dict[str, Any],
) -> None:
    """The latest export endpoint returns the current user's most recent request."""
    del migrated_database, export_test_context
    user_id = await create_verified_user("export-latest@auracles.space")

    first = await client.post(
        "/v1/gdpr/exports",
        headers=auth_headers(user_id),
    )
    first_id = first.json()["id"]
    async with async_session_factory() as session:
        first_request = await session.get(DataExportRequest, UUID(first_id))
        assert first_request is not None
        first_request.status = "ready"
        first_request.completed_at = datetime.now(UTC)
        await session.commit()

    second = await client.post(
        "/v1/gdpr/exports",
        headers=auth_headers(user_id),
    )
    latest = await client.get(
        "/v1/gdpr/exports/latest",
        headers=auth_headers(user_id),
    )

    assert second.status_code == 202
    assert latest.status_code == 200
    assert latest.json()["id"] == second.json()["id"]
    assert latest.json()["status"] == "pending"


async def test_generate_data_export_writes_redacted_json_bundle(
    migrated_database: None,
    export_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker writes a ready JSON bundle without secret-bearing fields."""
    del migrated_database, export_test_context
    fake_s3 = FakeS3Storage()
    monkeypatch.setattr(gdpr_beat.s3, "storage", fake_s3)
    user_id = await create_verified_user("export-worker@auracles.space")
    async with async_session_factory() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            assert user is not None
            user.password_hash = "HASH_SHOULD_NOT_EXPORT"
            user.totp_secret = "TOTP_SHOULD_NOT_EXPORT"
            request = DataExportRequest(user_id=user_id, status="pending")
            session.add(request)
            await session.flush()
            request_id = request.id
            session.add(
                AuditLog(
                    actor_id=user_id,
                    action="login_success",
                    target_type="user",
                    target_id=user_id,
                    metadata_={
                        "safe": "kept",
                        "email": "counterparty@example.com",
                        "summary": (
                            "Coordinate with counterparty@example.com using "
                            "https://counterparty.example.com/secure"
                        ),
                        "token": "TOKEN_SHOULD_NOT_EXPORT",
                    },
                )
            )

    result = await gdpr_beat._generate_data_export_impl(str(request_id))

    async with async_session_factory() as session:
        request = await session.get(DataExportRequest, request_id)
        ready_audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "gdpr_export_ready")
        )

    assert result["status"] == "ready"
    assert request is not None
    assert request.status == "ready"
    assert request.bundle_key == f"gdpr-exports/{user_id}/{request_id}.json"
    assert request.expires_at is not None
    assert ready_audit is not None
    assert fake_s3.uploads[0]["mime_type"] == "application/json"
    bundle = json.loads(fake_s3.uploads[0]["body"].decode("utf-8"))
    serialized_bundle = json.dumps(bundle)
    assert bundle["profile"]["email"] == "export-worker@auracles.space"
    assert bundle["security_audit"][0]["metadata"] == {"safe": "kept"}
    assert "HASH_SHOULD_NOT_EXPORT" not in serialized_bundle
    assert "TOTP_SHOULD_NOT_EXPORT" not in serialized_bundle
    assert "TOKEN_SHOULD_NOT_EXPORT" not in serialized_bundle
    assert "counterparty@example.com" not in serialized_bundle
    assert "counterparty.example.com" not in serialized_bundle


async def test_ready_export_download_redirects_to_private_presigned_url(
    client: AsyncClient,
    migrated_database: None,
    export_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ready export downloads redirect the owner to a private S3 URL."""
    del migrated_database, export_test_context
    fake_s3 = FakeS3Storage()
    monkeypatch.setattr(gdpr_beat.s3, "storage", fake_s3)
    user_id = await create_verified_user("export-download@auracles.space")
    async with async_session_factory() as session:
        async with session.begin():
            request = DataExportRequest(
                user_id=user_id,
                status="ready",
                bundle_key="gdpr-exports/test/export.json",
                completed_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            session.add(request)
            await session.flush()
            request_id = request.id

    response = await client.get(
        f"/v1/gdpr/exports/{request_id}/download",
        headers=auth_headers(user_id),
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert fake_s3.presigned_get_requests == [
        {
            "bucket": app.state.settings.s3_reports_bucket,
            "key": "gdpr-exports/test/export.json",
            "expires_in": 600,
            "download_name": "auracles-data-export.json",
        }
    ]
    assert (
        response.headers["location"]
        == (
            f"https://s3.test/{app.state.settings.s3_reports_bucket}/"
            "gdpr-exports/test/export.json"
            "?expires=600&download_name=auracles-data-export.json"
        )
    )


async def test_export_download_is_owner_scoped_and_ready_only(
    client: AsyncClient,
    migrated_database: None,
    export_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Download rejects non-owners, pending exports, and expired bundles."""
    del migrated_database, export_test_context
    fake_s3 = FakeS3Storage()
    monkeypatch.setattr(gdpr_beat.s3, "storage", fake_s3)
    owner_id = await create_verified_user("export-guard-owner@auracles.space")
    other_id = await create_verified_user("export-guard-other@auracles.space")
    async with async_session_factory() as session:
        async with session.begin():
            pending_request = DataExportRequest(
                user_id=owner_id,
                status="pending",
            )
            expired_request = DataExportRequest(
                user_id=owner_id,
                status="ready",
                bundle_key="gdpr-exports/test/expired-guard.json",
                completed_at=datetime.now(UTC) - timedelta(days=1),
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
            session.add_all([pending_request, expired_request])
            await session.flush()
            pending_request_id = pending_request.id
            expired_request_id = expired_request.id

    other_response = await client.get(
        f"/v1/gdpr/exports/{pending_request_id}/download",
        headers=auth_headers(other_id),
        follow_redirects=False,
    )
    pending_response = await client.get(
        f"/v1/gdpr/exports/{pending_request_id}/download",
        headers=auth_headers(owner_id),
        follow_redirects=False,
    )
    expired_response = await client.get(
        f"/v1/gdpr/exports/{expired_request_id}/download",
        headers=auth_headers(owner_id),
        follow_redirects=False,
    )

    assert other_response.status_code == 404
    assert pending_response.status_code == 409
    assert pending_response.json()["detail"] == "Data export is not ready for download."
    assert expired_response.status_code == 410
    assert expired_response.json()["detail"] == "Data export has expired."
    assert fake_s3.presigned_get_requests == []


async def test_export_download_is_rate_limited_per_user(
    client: AsyncClient,
    migrated_database: None,
    export_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Download throttles repeated presigned URL minting per user."""
    del migrated_database
    fake_s3 = FakeS3Storage()
    monkeypatch.setattr(gdpr_beat.s3, "storage", fake_s3)
    user_id = await create_verified_user("export-limit@auracles.space")
    async with async_session_factory() as session:
        async with session.begin():
            request = DataExportRequest(
                user_id=user_id,
                status="ready",
                bundle_key="gdpr-exports/test/rate-limit.json",
                completed_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            session.add(request)
            await session.flush()
            request_id = request.id

    for _ in range(gdpr_export_service.EXPORT_DOWNLOAD_LIMITER.limit):
        response = await client.get(
            f"/v1/gdpr/exports/{request_id}/download",
            headers=auth_headers(user_id),
            follow_redirects=False,
        )
        assert response.status_code == 302

    limited = await client.get(
        f"/v1/gdpr/exports/{request_id}/download",
        headers=auth_headers(user_id),
        follow_redirects=False,
    )

    assert limited.status_code == 429
    assert limited.json()["detail"] == "Rate limit exceeded."
    assert (
        export_test_context["redis"].ttls[
            f"rate_limit:gdpr_export_download:{user_id}"
        ]
        == gdpr_export_service.EXPORT_DOWNLOAD_LIMITER.window
    )


async def test_expire_data_exports_deletes_bundle_and_marks_request_expired(
    migrated_database: None,
    export_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Daily GDPR export expiry deletes past-due bundles and updates status."""
    del migrated_database, export_test_context
    fake_s3 = FakeS3Storage()
    monkeypatch.setattr(gdpr_beat.s3, "storage", fake_s3)
    user_id = await create_verified_user("export-expiry@auracles.space")
    async with async_session_factory() as session:
        async with session.begin():
            expired_request = DataExportRequest(
                user_id=user_id,
                status="ready",
                bundle_key="gdpr-exports/test/expired.json",
                completed_at=datetime.now(UTC) - timedelta(days=2),
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
            active_request = DataExportRequest(
                user_id=user_id,
                status="ready",
                bundle_key="gdpr-exports/test/active.json",
                completed_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            session.add_all([expired_request, active_request])
            await session.flush()
            expired_request_id = expired_request.id
            active_request_id = active_request.id

    result = await gdpr_beat._expire_data_exports_impl()

    async with async_session_factory() as session:
        expired_request = await session.get(DataExportRequest, expired_request_id)
        active_request = await session.get(DataExportRequest, active_request_id)

    assert result == {"expired_count": 1}
    assert expired_request is not None
    assert expired_request.status == "expired"
    assert expired_request.bundle_key is None
    assert active_request is not None
    assert active_request.status == "ready"
    assert active_request.bundle_key == "gdpr-exports/test/active.json"
    assert fake_s3.deleted_objects == [
        (app.state.settings.s3_reports_bucket, "gdpr-exports/test/expired.json")
    ]
