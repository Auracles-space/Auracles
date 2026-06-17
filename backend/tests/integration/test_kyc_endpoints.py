"""Integration tests for KYC upload, submission, and admin review."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, select

from app.core.database import async_session_factory, engine
from app.core.dependencies import require_kyc_verified
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import KycDocument, User, UserRole
from app.modules.notifications.models import Notification
from app.modules.settings import service as settings_service
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async


class FakeRedis:
    """Minimal Redis override for authenticated settings routes."""


class FakeKycStorage:
    """S3 storage test double for KYC object existence checks."""

    def __init__(self) -> None:
        """Create empty fake S3 state."""
        self.existing_keys: set[str] = set()
        self.presigned_requests: list[tuple[str, str, str, int, int]] = []

    def presigned_post(
        self,
        bucket: str,
        key: str,
        mime_type: str,
        max_size: int,
        expires_in: int,
    ) -> dict[str, Any]:
        """Return a deterministic fake KYC presigned POST policy."""
        self.presigned_requests.append((bucket, key, mime_type, max_size, expires_in))
        return {
            "url": f"https://s3.test/{bucket}",
            "fields": {
                "key": key,
                "Content-Type": mime_type,
                "policy": "fake-policy",
                "x-amz-signature": "fake-signature",
            },
        }

    def object_exists(self, bucket: str, key: str) -> bool:
        """Return whether the fake object was marked uploaded."""
        return key in self.existing_keys


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure KYC tables exist for endpoint tests."""
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
async def kyc_test_context() -> AsyncIterator[dict[str, Any]]:
    """Reset auth/KYC state and install a Redis override."""
    fake_storage = FakeKycStorage()
    await engine.dispose()

    async def cleanup() -> None:
        """Delete KYC and identity rows in FK-safe order."""
        async with async_session_factory() as session:
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()

    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    original_storage = settings_service.s3.storage
    settings_service.s3.storage = fake_storage
    try:
        yield {"storage": fake_storage}
    finally:
        settings_service.s3.storage = original_storage
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def create_user_with_roles(email: str, roles: list[str]) -> UUID:
    """Create a verified user with approved roles for KYC tests."""
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
            for role in roles:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        approved_at=datetime.now(UTC),
                    )
                )
        return user.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_user_can_request_kyc_upload_url_and_view_pending_status(
    client: AsyncClient,
    migrated_database: None,
    kyc_test_context: dict[str, Any],
) -> None:
    """Authenticated users can request a constrained KYC upload target."""
    user_id = await create_user_with_roles("kyc@auracles.space", ["operator"])

    response = await client.post(
        "/v1/settings/kyc/upload-url",
        json={
            "doc_type": "passport",
            "mime_type": "application/pdf",
            "file_size": 1024,
        },
        headers=auth_headers(user_id, ["operator"]),
    )
    status_response = await client.get(
        "/v1/settings/kyc",
        headers=auth_headers(user_id, ["operator"]),
    )

    assert response.status_code == 200
    assert response.json()["upload_url"].startswith(("http://", "https://"))
    assert response.json()["s3_key"].startswith(f"kyc/{user_id}/")
    assert response.json()["fields"]["key"] == response.json()["s3_key"]
    assert response.json()["fields"]["Content-Type"] == "application/pdf"
    assert response.json()["fields"]["policy"] == "fake-policy"
    assert status_response.status_code == 200
    assert status_response.json()["kyc_status"] == "unverified"
    assert len(status_response.json()["documents"]) == 1


async def test_kyc_submit_requires_uploaded_object_then_marks_status_pending(
    client: AsyncClient,
    migrated_database: None,
    kyc_test_context: dict[str, Any],
) -> None:
    """KYC submit fails before upload and succeeds once S3 confirms the object."""
    user_id = await create_user_with_roles("submit-kyc@auracles.space", ["operator"])
    headers = auth_headers(user_id, ["operator"])
    upload = await client.post(
        "/v1/settings/kyc/upload-url",
        json={
            "doc_type": "national_id",
            "mime_type": "image/png",
            "file_size": 2048,
        },
        headers=headers,
    )
    s3_key = upload.json()["s3_key"]

    before_upload = await client.post(
        "/v1/settings/kyc/submit",
        json={"s3_key": s3_key},
        headers=headers,
    )
    kyc_test_context["storage"].existing_keys.add(s3_key)
    submitted = await client.post(
        "/v1/settings/kyc/submit",
        json={"s3_key": s3_key},
        headers=headers,
    )

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        audit_log = await session.scalar(
            select(AuditLog).where(AuditLog.action == "kyc_status_change")
        )

    assert before_upload.status_code == 409
    assert submitted.status_code == 200
    assert submitted.json()["kyc_status"] == "pending"
    assert user is not None
    assert user.kyc_status == "pending"
    assert audit_log is not None


async def test_admin_can_verify_kyc_and_dependency_allows_verified_user(
    client: AsyncClient,
    migrated_database: None,
    kyc_test_context: dict[str, Any],
) -> None:
    """Admin KYC review updates status and satisfies the shared KYC dependency."""
    user_id = await create_user_with_roles("verify-kyc@auracles.space", ["operator"])
    admin_id = await create_user_with_roles("kyc-admin@auracles.space", ["admin"])
    user_headers = auth_headers(user_id, ["operator"])
    upload = await client.post(
        "/v1/settings/kyc/upload-url",
        json={
            "doc_type": "drivers_license",
            "mime_type": "image/jpeg",
            "file_size": 4096,
        },
        headers=user_headers,
    )
    s3_key = upload.json()["s3_key"]
    kyc_test_context["storage"].existing_keys.add(s3_key)
    await client.post(
        "/v1/settings/kyc/submit",
        json={"s3_key": s3_key},
        headers=user_headers,
    )

    response = await client.patch(
        f"/v1/admin/users/{user_id}/kyc",
        json={"status": "verified", "notes": "Reviewed."},
        headers=auth_headers(admin_id, ["admin"]),
    )

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        document = await session.scalar(
            select(KycDocument).where(KycDocument.user_id == user_id)
        )
        audit_log = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "kyc_status_change",
                AuditLog.actor_id == admin_id,
            )
        )
        allowed_user = await require_kyc_verified(user)  # type: ignore[arg-type]

    assert response.status_code == 200
    assert response.json()["kyc_status"] == "verified"
    assert user is not None
    assert document is not None
    assert user.kyc_status == "verified"
    assert document.status == "verified"
    assert document.reviewed_by == admin_id
    assert audit_log is not None
    assert allowed_user.id == user_id


@pytest.mark.asyncio
async def test_admin_kyc_review_notifies_reviewed_user(
    client: AsyncClient,
    migrated_database: None,
    kyc_test_context: dict[str, Any],
) -> None:
    """A KYC review creates a durable in-app notification for the user.

    The verdict (verified/rejected) drives the notification type so the user
    learns the outcome without polling. Covers the async admin-approval UX.
    """
    user_id = await create_user_with_roles("notify-kyc@auracles.space", ["operator"])
    admin_id = await create_user_with_roles("kyc-admin2@auracles.space", ["admin"])
    user_headers = auth_headers(user_id, ["operator"])
    upload = await client.post(
        "/v1/settings/kyc/upload-url",
        json={"doc_type": "passport", "mime_type": "image/jpeg", "file_size": 4096},
        headers=user_headers,
    )
    s3_key = upload.json()["s3_key"]
    kyc_test_context["storage"].existing_keys.add(s3_key)
    await client.post(
        "/v1/settings/kyc/submit",
        json={"s3_key": s3_key},
        headers=user_headers,
    )

    response = await client.patch(
        f"/v1/admin/users/{user_id}/kyc",
        json={"status": "verified", "notes": "Reviewed."},
        headers=auth_headers(admin_id, ["admin"]),
    )

    async with async_session_factory() as session:
        notification = await session.scalar(
            select(Notification).where(Notification.user_id == user_id)
        )

    assert response.status_code == 200
    assert notification is not None
    assert notification.notification_type == "kyc_verified"
    assert notification.link == "/settings/kyc"


async def test_kyc_upload_rejects_bad_mime_and_large_file(
    client: AsyncClient,
    migrated_database: None,
    kyc_test_context: dict[str, Any],
) -> None:
    """KYC upload-url validates MIME allowlist and max file size."""
    user_id = await create_user_with_roles("bad-kyc@auracles.space", ["operator"])
    headers = auth_headers(user_id, ["operator"])

    bad_mime = await client.post(
        "/v1/settings/kyc/upload-url",
        json={
            "doc_type": "passport",
            "mime_type": "text/plain",
            "file_size": 1024,
        },
        headers=headers,
    )
    too_large = await client.post(
        "/v1/settings/kyc/upload-url",
        json={
            "doc_type": "passport",
            "mime_type": "application/pdf",
            "file_size": 10 * 1024 * 1024 + 1,
        },
        headers=headers,
    )

    assert bad_mime.status_code == 415
    assert too_large.status_code == 413
