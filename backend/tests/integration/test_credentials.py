"""Integration tests for Phase 4b Credential management."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.integrations import s3
from app.main import app
from app.modules.attestation import credential_service
from app.modules.attestation.models import AttestationUploadSession, Credential
from app.modules.auth.models import User, UserRole
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for routes that do not use Redis directly."""


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Phase 4b credential tables exist for endpoint tests."""
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
async def credential_context() -> AsyncIterator[FakeRedis]:
    """Reset credential/auth state and install a Redis test double."""
    fake_redis = FakeRedis()
    await engine.dispose()
    await reset_credential_state()

    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await reset_credential_state()
        await engine.dispose()


async def reset_credential_state() -> None:
    """Remove credential test rows in dependency order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(Credential))
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


async def create_user(email: str, roles: list[str]) -> UUID:
    """Create a verified user with approved role rows."""
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


def credential_payload() -> dict[str, object]:
    """Return a valid Credential create payload."""
    return {
        "title": "Certified Healthcare Operations Lead",
        "issuer": "Global Health Institute",
        "issued_date": "2024-05-01",
        "expires_date": "2029-05-01",
    }


async def test_user_manages_only_their_own_credentials(
    client: AsyncClient,
    migrated_database: None,
    credential_context: FakeRedis,
) -> None:
    """Users can CRUD own Credentials while other users are denied."""
    del migrated_database, credential_context
    owner_id = await create_user("credential-owner@auracles.space", ["operator"])
    outsider_id = await create_user("credential-outsider@auracles.space", ["operator"])
    owner_headers = auth_headers(owner_id, ["operator"])
    outsider_headers = auth_headers(outsider_id, ["operator"])

    created = await client.post(
        "/v1/credentials",
        headers=owner_headers,
        json=credential_payload(),
    )
    assert created.status_code == 201

    credential_id = created.json()["id"]
    listed = await client.get("/v1/credentials", headers=owner_headers)
    outsider_listed = await client.get("/v1/credentials", headers=outsider_headers)
    outsider_update = await client.patch(
        f"/v1/credentials/{credential_id}",
        headers=outsider_headers,
        json={"title": "Attempted takeover"},
    )
    updated = await client.patch(
        f"/v1/credentials/{credential_id}",
        headers=owner_headers,
        json={"title": "Certified Healthcare Transformation Lead"},
    )
    deleted = await client.delete(
        f"/v1/credentials/{credential_id}",
        headers=owner_headers,
    )
    listed_after_delete = await client.get("/v1/credentials", headers=owner_headers)

    async with async_session_factory() as session:
        stored = await session.get(Credential, UUID(credential_id))
        audits = (
            await session.execute(
                select(AuditLog.action).where(AuditLog.target_type == "credential")
            )
        ).scalars().all()

    assert created.json()["user_id"] == str(owner_id)
    assert created.json()["title"] == "Certified Healthcare Operations Lead"
    assert created.json()["evidence_file_keys"] == []
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["credentials"]] == [
        credential_id
    ]
    assert outsider_listed.status_code == 200
    assert outsider_listed.json()["credentials"] == []
    assert outsider_update.status_code == 404
    assert updated.status_code == 200
    assert updated.json()["title"] == "Certified Healthcare Transformation Lead"
    assert deleted.status_code == 204
    assert listed_after_delete.json()["credentials"] == []
    assert stored is None
    assert set(audits) == {"credential_created", "credential_deleted"}


async def test_credential_evidence_upload_session_controls_attached_keys(
    client: AsyncClient,
    migrated_database: None,
    credential_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Credential evidence keys must come from owned, unexpired upload sessions."""
    del migrated_database, credential_context
    presigned_calls: list[tuple[str, str, str, int, int]] = []
    dispatched_scans: list[str] = []

    def fake_presigned_post(
        bucket: str,
        key: str,
        mime_type: str,
        max_size: int,
        expires_in: int,
    ) -> dict[str, object]:
        """Return deterministic S3 POST data without contacting AWS."""
        presigned_calls.append((bucket, key, mime_type, max_size, expires_in))
        return {
            "url": f"https://s3.local/{bucket}",
            "fields": {
                "key": key,
                "Content-Type": mime_type,
                "max_size": str(max_size),
                "expires_in": str(expires_in),
            },
        }

    monkeypatch.setattr(
        s3.storage,
        "presigned_post",
        fake_presigned_post,
    )

    class FakeScanTask:
        """Capture queued Credential evidence scan tasks without running Celery."""

        @staticmethod
        def delay(upload_session_id: str) -> None:
            dispatched_scans.append(upload_session_id)

    monkeypatch.setattr(credential_service, "scan_attestation_upload", FakeScanTask)

    owner_id = await create_user("credential-evidence@auracles.space", ["operator"])
    owner_headers = auth_headers(owner_id, ["operator"])
    created = await client.post(
        "/v1/credentials",
        headers=owner_headers,
        json=credential_payload(),
    )
    credential_id = created.json()["id"]

    arbitrary_key = await client.patch(
        f"/v1/credentials/{credential_id}",
        headers=owner_headers,
        json={"evidence_file_keys": ["credentials/fake.pdf"]},
    )
    upload = await client.post(
        f"/v1/credentials/{credential_id}/uploads",
        headers=owner_headers,
        json={
            "file_name": "credential evidence.pdf",
            "content_type": "application/pdf",
            "size_bytes": 1200,
        },
    )
    assert upload.status_code == 201

    evidence_key = upload.json()["s3_key"]
    pending_attachment = await client.patch(
        f"/v1/credentials/{credential_id}",
        headers=owner_headers,
        json={"evidence_file_keys": [evidence_key]},
    )

    async with async_session_factory() as session:
        upload_session = await session.scalar(
            select(AttestationUploadSession).where(
                AttestationUploadSession.s3_key == evidence_key
            )
        )
        assert upload_session is not None
        upload_session_id = upload_session.id

    async with async_session_factory() as session:
        async with session.begin():
            upload_session = await session.scalar(
                select(AttestationUploadSession).where(
                    AttestationUploadSession.s3_key == evidence_key
                )
            )
            assert upload_session is not None
            upload_session.scan_status = "clean"

    attached = await client.patch(
        f"/v1/credentials/{credential_id}",
        headers=owner_headers,
        json={"evidence_file_keys": [evidence_key]},
    )
    reused = await client.patch(
        f"/v1/credentials/{credential_id}",
        headers=owner_headers,
        json={"evidence_file_keys": [evidence_key]},
    )

    async with async_session_factory() as session:
        upload_session = await session.scalar(select(AttestationUploadSession))
        stored = await session.get(Credential, UUID(credential_id))

    assert arbitrary_key.status_code == 422
    assert upload.json()["url"] == "https://s3.local/auracles-artifacts-dev"
    assert upload.json()["size_limit"] == 10 * 1024 * 1024
    assert evidence_key.startswith(f"credentials/{credential_id}/{owner_id}/")
    assert pending_attachment.status_code == 409
    assert dispatched_scans == [str(upload_session_id)]
    assert presigned_calls == [
        (
            "auracles-artifacts-dev",
            evidence_key,
            "application/pdf",
            10 * 1024 * 1024,
            300,
        )
    ]
    assert attached.status_code == 200
    assert attached.json()["evidence_file_keys"] == [evidence_key]
    assert reused.status_code == 422
    assert upload_session is not None
    assert upload_session.credential_id == UUID(credential_id)
    assert upload_session.attestation_id is None
    assert upload_session.purpose == "credential_evidence"
    assert upload_session.scan_status == "clean"
    assert upload_session.consumed_at is not None
    assert stored is not None
    assert stored.evidence_file_keys == [evidence_key]
