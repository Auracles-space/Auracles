"""Integration tests for manual Credential verification (Admin-driven)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from httpx import AsyncClient  # noqa: F401
from sqlalchemy import create_engine, delete, inspect, select  # noqa: F401

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    encrypt_totp_secret,
    hash_password,
)
from app.main import app
from app.modules.attestation import credential_service
from app.modules.attestation.models import AttestationUploadSession, Credential
from app.modules.auth.models import User, UserRole
from app.shared.models.audit_log import AuditLog
from tests.conftest import open_step_up_window


class FakeRedis:
    """Redis test double backing the admin step-up window on credential reviews.

    Credential verify/reject require an open step-up window
    (``require_step_up``), which tests seed with ``open_step_up_window``.
    """

    def __init__(self) -> None:
        """Create empty in-memory Redis state."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}

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
        """Store a string value with a TTL (test double ignores expiry)."""
        del seconds
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        """Return a stored value or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def incr(self, key: str) -> int:
        """Increment and return a counter."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """Record a TTL for a key."""
        self.ttls[key] = seconds

    async def ttl(self, key: str) -> int:
        """Return a recorded TTL, or -1 when none was set."""
        return self.ttls.get(key, -1)

    async def delete(self, *keys: str) -> int:
        """Delete stored values and counters."""
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.counters)
            self.values.pop(key, None)
            self.counters.pop(key, None)
            self.ttls.pop(key, None)
        return removed


async def enable_admin_totp(user_id: UUID) -> None:
    """Enrol a user in TOTP so ``require_step_up`` can accept a seeded window."""
    async with async_session_factory() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            assert user is not None
            user.totp_secret = encrypt_totp_secret(pyotp.random_base32())
            user.totp_enabled = True


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure credential tables exist for endpoint tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url, pool_pre_ping=True
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


async def reset_credential_state() -> None:
    """Remove credential test rows in dependency order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(Credential))
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


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
                    UserRole(user_id=user.id, role=role, approved_at=datetime.now(UTC))
                )
        return user.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


def test_credentials_table_has_verification_columns(migrated_database: None) -> None:
    """Migration adds verification + metadata columns to credentials."""
    del migrated_database
    sync_engine = create_engine(app.state.settings.sync_database_url)
    try:
        columns = {
            col["name"] for col in inspect(sync_engine).get_columns("credentials")
        }
    finally:
        sync_engine.dispose()
    assert {
        "verification_status",
        "credential_type",
        "verification_url",
        "reference_number",
        "issuer_type",
        "submitted_at",
        "verified_at",
        "reviewed_by",
        "rejection_reason",
    } <= columns


async def _seed_credential(user_id: UUID, **kwargs) -> UUID:
    async with async_session_factory() as session:
        async with session.begin():
            credential = Credential(
                user_id=user_id,
                title=kwargs.pop("title", "PMP"),
                issuer=kwargs.pop("issuer", "PMI"),
                issued_date=kwargs.pop("issued_date", date(2024, 1, 1)),
                **kwargs,
            )
            session.add(credential)
            await session.flush()
            return credential.id


async def test_submit_requires_evidence(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """Submitting a credential with no evidence/url/reference is rejected 422."""
    del migrated_database, credential_context
    user_id = await create_user("submit-noev@auracles.space", ["contributor"])
    credential_id = await _seed_credential(user_id)
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        with pytest.raises(HTTPException) as exc:
            await credential_service.submit_credential(
                db=session, user=user, credential_id=credential_id
            )
    assert exc.value.status_code == 422


async def test_submit_transitions_to_pending(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """A credential with a reference number can be submitted -> pending."""
    del migrated_database, credential_context
    user_id = await create_user("submit-ok@auracles.space", ["contributor"])
    credential_id = await _seed_credential(user_id, reference_number="PMP-1")
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        result = await credential_service.submit_credential(
            db=session, user=user, credential_id=credential_id
        )
    assert result.verification_status == "pending"
    assert result.submitted_at is not None


async def test_submit_blocked_when_already_verified(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """Submitting an already-verified credential raises 422."""
    del migrated_database, credential_context
    user_id = await create_user("submit-verified@auracles.space", ["contributor"])
    credential_id = await _seed_credential(
        user_id, reference_number="PMP-1", verification_status="verified"
    )
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        with pytest.raises(HTTPException) as exc:
            await credential_service.submit_credential(
                db=session, user=user, credential_id=credential_id
            )
    assert exc.value.status_code == 422


async def test_verify_only_from_pending(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """verify_credential promotes pending -> verified and stamps reviewer."""
    del migrated_database, credential_context
    admin_id = await create_user("verify-admin@auracles.space", ["admin"])
    owner_id = await create_user("verify-owner@auracles.space", ["contributor"])
    credential_id = await _seed_credential(
        owner_id, reference_number="PMP-1", verification_status="pending"
    )
    async with async_session_factory() as session:
        result = await credential_service.verify_credential(
            db=session,
            admin_id=admin_id,
            credential_id=credential_id,
        )
    assert result.verification_status == "verified"
    assert result.verified_at is not None
    assert result.reviewed_by == admin_id


async def test_verify_rejects_non_pending(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """Verifying a non-pending credential raises 422."""
    del migrated_database, credential_context
    admin_id = await create_user("verify-admin2@auracles.space", ["admin"])
    owner_id = await create_user("verify-owner2@auracles.space", ["contributor"])
    credential_id = await _seed_credential(owner_id, reference_number="PMP-1")
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await credential_service.verify_credential(
                db=session,
                admin_id=admin_id,
                credential_id=credential_id,
            )
    assert exc.value.status_code == 422


async def test_reject_requires_pending_and_sets_reason(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """reject_credential moves pending -> rejected and stores the reason."""
    del migrated_database, credential_context
    admin_id = await create_user("reject-admin@auracles.space", ["admin"])
    owner_id = await create_user("reject-owner@auracles.space", ["contributor"])
    credential_id = await _seed_credential(
        owner_id, reference_number="PMP-1", verification_status="pending"
    )
    async with async_session_factory() as session:
        result = await credential_service.reject_credential(
            db=session,
            admin_id=admin_id,
            credential_id=credential_id,
            reason="Issuer could not confirm.",
        )
    assert result.verification_status == "rejected"
    assert result.rejection_reason == "Issuer could not confirm."
    assert result.reviewed_by == admin_id


async def test_editing_material_field_resets_verification(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """Editing title on a verified credential resets it to unverified."""
    del migrated_database, credential_context
    owner_id = await create_user("reset-owner@auracles.space", ["contributor"])
    credential_id = await _seed_credential(
        owner_id,
        reference_number="PMP-1",
        verification_status="verified",
    )
    from app.modules.attestation.schemas import CredentialUpdateRequest

    async with async_session_factory() as session:
        user = await session.get(User, owner_id)
        result = await credential_service.update_credential(
            db=session,
            user=user,
            credential_id=credential_id,
            payload=CredentialUpdateRequest(title="PMP Renewed"),
        )
    assert result.verification_status == "unverified"
    assert result.verified_at is None
    assert result.reviewed_by is None


async def test_editing_non_material_field_keeps_verification(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """Editing expires_date does not reset a verified credential."""
    del migrated_database, credential_context
    owner_id = await create_user("keep-owner@auracles.space", ["contributor"])
    credential_id = await _seed_credential(
        owner_id, reference_number="PMP-1", verification_status="verified"
    )
    from app.modules.attestation.schemas import CredentialUpdateRequest

    async with async_session_factory() as session:
        user = await session.get(User, owner_id)
        result = await credential_service.update_credential(
            db=session,
            user=user,
            credential_id=credential_id,
            payload=CredentialUpdateRequest(
                expires_date=(date.today() + timedelta(days=365 * 3)).isoformat()
            ),
        )
    assert result.verification_status == "verified"


async def test_submit_endpoint_owner_only(
    client: AsyncClient, migrated_database: None, credential_context: FakeRedis
) -> None:
    """Owner can submit; a non-owner gets 404; response carries verification_status."""
    del migrated_database, credential_context
    owner_id = await create_user("ep-owner@auracles.space", ["contributor"])
    outsider_id = await create_user("ep-outsider@auracles.space", ["contributor"])
    credential_id = str(await _seed_credential(owner_id, reference_number="PMP-1"))

    outsider = await client.post(
        f"/v1/credentials/{credential_id}/submit",
        headers=auth_headers(outsider_id, ["contributor"]),
    )
    owner = await client.post(
        f"/v1/credentials/{credential_id}/submit",
        headers=auth_headers(owner_id, ["contributor"]),
    )
    assert outsider.status_code == 404
    assert owner.status_code == 200
    assert owner.json()["verification_status"] == "pending"
    assert owner.json()["expired"] is False


async def test_admin_queue_and_decisions(
    client: AsyncClient, migrated_database: None, credential_context: FakeRedis
) -> None:
    """Admin lists pending queue and verifies; non-admin is forbidden."""
    del migrated_database
    admin_id = await create_user("queue-admin@auracles.space", ["admin"])
    await enable_admin_totp(admin_id)
    await open_step_up_window(credential_context, admin_id)
    owner_id = await create_user("queue-owner@auracles.space", ["contributor"])
    credential_id = str(
        await _seed_credential(
            owner_id, reference_number="PMP-1", verification_status="pending"
        )
    )

    forbidden = await client.get(
        "/v1/admin/credentials",
        headers=auth_headers(owner_id, ["contributor"]),
    )
    queue = await client.get(
        "/v1/admin/credentials?status=pending",
        headers=auth_headers(admin_id, ["admin"]),
    )
    verified = await client.post(
        f"/v1/admin/credentials/{credential_id}/verify",
        headers=auth_headers(admin_id, ["admin"]),
        json={},
    )

    assert forbidden.status_code == 403
    assert queue.status_code == 200
    assert credential_id in [c["id"] for c in queue.json()["credentials"]]
    assert verified.status_code == 200
    assert verified.json()["verification_status"] == "verified"


async def test_admin_reject_requires_reason(
    client: AsyncClient, migrated_database: None, credential_context: FakeRedis
) -> None:
    """Admin reject with empty reason is a 422; with reason it succeeds."""
    del migrated_database
    admin_id = await create_user("rej-admin@auracles.space", ["admin"])
    await enable_admin_totp(admin_id)
    await open_step_up_window(credential_context, admin_id)
    owner_id = await create_user("rej-owner@auracles.space", ["contributor"])
    credential_id = str(
        await _seed_credential(
            owner_id, reference_number="PMP-1", verification_status="pending"
        )
    )

    empty = await client.post(
        f"/v1/admin/credentials/{credential_id}/reject",
        headers=auth_headers(admin_id, ["admin"]),
        json={"reason": ""},
    )
    ok = await client.post(
        f"/v1/admin/credentials/{credential_id}/reject",
        headers=auth_headers(admin_id, ["admin"]),
        json={"reason": "Issuer registry shows no match."},
    )
    assert empty.status_code == 422
    assert ok.status_code == 200
    assert ok.json()["verification_status"] == "rejected"


async def test_admin_credential_decisions_require_step_up_window(
    client: AsyncClient, migrated_database: None, credential_context: FakeRedis
) -> None:
    """Verify/reject answer 403 without an open step-up window.

    An enrolled admin with no window gets ``step_up_required``; an admin who
    has not enrolled in 2FA gets ``totp_setup_required``. The credential is
    left pending either way.
    """
    del migrated_database, credential_context
    enrolled_id = await create_user("stepup-admin@auracles.space", ["admin"])
    await enable_admin_totp(enrolled_id)
    unenrolled_id = await create_user("no2fa-admin@auracles.space", ["admin"])
    owner_id = await create_user("stepup-owner@auracles.space", ["contributor"])
    credential_id = str(
        await _seed_credential(
            owner_id, reference_number="PMP-1", verification_status="pending"
        )
    )

    no_window_verify = await client.post(
        f"/v1/admin/credentials/{credential_id}/verify",
        headers=auth_headers(enrolled_id, ["admin"]),
        json={},
    )
    no_window_reject = await client.post(
        f"/v1/admin/credentials/{credential_id}/reject",
        headers=auth_headers(enrolled_id, ["admin"]),
        json={"reason": "Issuer registry shows no match."},
    )
    unenrolled_verify = await client.post(
        f"/v1/admin/credentials/{credential_id}/verify",
        headers=auth_headers(unenrolled_id, ["admin"]),
        json={},
    )

    assert no_window_verify.status_code == 403
    assert no_window_verify.json()["detail"]["error_code"] == "step_up_required"
    assert no_window_reject.status_code == 403
    assert no_window_reject.json()["detail"]["error_code"] == "step_up_required"
    assert unenrolled_verify.status_code == 403
    assert unenrolled_verify.json()["detail"]["error_code"] == "totp_setup_required"
    async with async_session_factory() as session:
        credential = await session.get(Credential, UUID(credential_id))
    assert credential is not None
    assert credential.verification_status == "pending"


async def test_verify_blocks_admin_self_review(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """An admin who owns a credential cannot self-verify it (403)."""
    del migrated_database, credential_context
    admin_id = await create_user(
        "self-verify-admin@auracles.space", ["admin", "contributor"]
    )
    credential_id = await _seed_credential(
        admin_id, reference_number="PMP-1", verification_status="pending"
    )
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await credential_service.verify_credential(
                db=session,
                admin_id=admin_id,
                credential_id=credential_id,
            )
    assert exc.value.status_code == 403


async def test_reject_blocks_admin_self_review(
    migrated_database: None, credential_context: FakeRedis
) -> None:
    """An admin who owns a credential cannot self-reject it (403)."""
    del migrated_database, credential_context
    admin_id = await create_user(
        "self-reject-admin@auracles.space", ["admin", "contributor"]
    )
    credential_id = await _seed_credential(
        admin_id, reference_number="PMP-1", verification_status="pending"
    )
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await credential_service.reject_credential(
                db=session,
                admin_id=admin_id,
                credential_id=credential_id,
                reason="should not be allowed",
            )
    assert exc.value.status_code == 403


def _fake_presigned_get(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub S3 presigned GET so no AWS call happens during download tests."""
    from app.integrations import s3

    async def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool:
        """Store a string value, optionally respecting NX semantics."""
        del ex
        store = self.__dict__.setdefault("values", {})
        if nx and key in store:
            return False
        store[key] = value
        return True

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a string value with a TTL (test double ignores expiry)."""
        del seconds
        self.__dict__.setdefault("values", {})[key] = value

    def fake_presigned_get(
        bucket: str,
        key: str,
        expires_in: int,
        *,
        download_name: str | None = None,
    ) -> str:
        return "https://signed.example/evidence"

    monkeypatch.setattr(s3.storage, "presigned_get", fake_presigned_get)


async def test_owner_downloads_own_evidence_download(
    client: AsyncClient,
    migrated_database: None,
    credential_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owner downloads own evidence -> 200 with a presigned url."""
    del migrated_database, credential_context
    _fake_presigned_get(monkeypatch)
    owner_id = await create_user("ev-owner@auracles.space", ["contributor"])
    key = "credentials/abc/def/file.pdf"
    credential_id = str(await _seed_credential(owner_id, evidence_file_keys=[key]))
    resp = await client.get(
        f"/v1/credentials/{credential_id}/evidence",
        params={"key": key},
        headers=auth_headers(owner_id, ["contributor"]),
    )
    assert resp.status_code == 200
    assert resp.json()["url"].startswith("https://")


async def test_admin_downloads_any_evidence_download(
    client: AsyncClient,
    migrated_database: None,
    credential_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admin downloads any credential's evidence -> 200."""
    del migrated_database, credential_context
    _fake_presigned_get(monkeypatch)
    owner_id = await create_user("ev-owner2@auracles.space", ["contributor"])
    admin_id = await create_user("ev-admin@auracles.space", ["admin"])
    key = "credentials/abc/def/file.pdf"
    credential_id = str(await _seed_credential(owner_id, evidence_file_keys=[key]))
    resp = await client.get(
        f"/v1/admin/credentials/{credential_id}/evidence",
        params={"key": key},
        headers=auth_headers(admin_id, ["admin"]),
    )
    assert resp.status_code == 200
    assert resp.json()["url"].startswith("https://")


async def test_stranger_cannot_download_evidence_download(
    client: AsyncClient,
    migrated_database: None,
    credential_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-owner, non-admin user is denied (403) on the owner route."""
    del migrated_database, credential_context
    _fake_presigned_get(monkeypatch)
    owner_id = await create_user("ev-owner3@auracles.space", ["contributor"])
    stranger_id = await create_user("ev-stranger@auracles.space", ["contributor"])
    key = "credentials/abc/def/file.pdf"
    credential_id = str(await _seed_credential(owner_id, evidence_file_keys=[key]))
    resp = await client.get(
        f"/v1/credentials/{credential_id}/evidence",
        params={"key": key},
        headers=auth_headers(stranger_id, ["contributor"]),
    )
    assert resp.status_code == 403


async def test_unknown_key_not_found_evidence_download(
    client: AsyncClient,
    migrated_database: None,
    credential_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key not present on the credential -> 404."""
    del migrated_database, credential_context
    _fake_presigned_get(monkeypatch)
    owner_id = await create_user("ev-owner4@auracles.space", ["contributor"])
    credential_id = str(
        await _seed_credential(
            owner_id, evidence_file_keys=["credentials/abc/def/real.pdf"]
        )
    )
    resp = await client.get(
        f"/v1/credentials/{credential_id}/evidence",
        params={"key": "credentials/abc/def/missing.pdf"},
        headers=auth_headers(owner_id, ["contributor"]),
    )
    assert resp.status_code == 404


async def test_evidence_download_writes_audit(
    client: AsyncClient,
    migrated_database: None,
    credential_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful download writes a credential_evidence_download audit row."""
    del migrated_database, credential_context
    _fake_presigned_get(monkeypatch)
    owner_id = await create_user("ev-owner5@auracles.space", ["contributor"])
    key = "credentials/abc/def/file.pdf"
    credential_id = str(await _seed_credential(owner_id, evidence_file_keys=[key]))
    resp = await client.get(
        f"/v1/credentials/{credential_id}/evidence",
        params={"key": key},
        headers=auth_headers(owner_id, ["contributor"]),
    )
    assert resp.status_code == 200
    async with async_session_factory() as session:
        actions = (
            (
                await session.execute(
                    select(AuditLog.action).where(AuditLog.target_type == "credential")
                )
            )
            .scalars()
            .all()
        )
    assert "credential_evidence_download" in actions
