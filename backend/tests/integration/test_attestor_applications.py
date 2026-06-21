"""Integration tests for Phase 4b Attestor application workflows."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import UUID

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.attestation.models import (
    AttestationUploadSession,
    AttestorApplication,
    AttestorProfile,
)
from app.modules.auth.models import User, UserRole
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for routes that do not need external Redis."""

    def __init__(self) -> None:
        """Create empty in-memory Redis state."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}

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

    async def delete(self, *keys: str) -> int:
        """Delete stored values and counters."""
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.counters)
            self.values.pop(key, None)
            self.counters.pop(key, None)
            self.ttls.pop(key, None)
        return removed


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Phase 4b attestation tables exist for endpoint tests."""
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
async def attestor_application_context() -> AsyncIterator[FakeRedis]:
    """Reset attestation/auth state and install a Redis test double."""
    fake_redis = FakeRedis()
    await engine.dispose()
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(AttestorProfile))
            await session.execute(delete(AttestorApplication))
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))

    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(delete(AttestationUploadSession))
                await session.execute(delete(AttestorProfile))
                await session.execute(delete(AttestorApplication))
                await session.execute(delete(AuditLog))
                await session.execute(delete(UserRole))
                await session.execute(delete(User))
        await engine.dispose()


async def create_user(email: str, roles: list[str]) -> UUID:
    """Create a verified user with approved role rows for auth tests."""
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


async def create_admin_user() -> tuple[UUID, str]:
    """Create an admin user with TOTP enabled for sensitive review routes."""
    secret = pyotp.random_base32()
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email="attestor-review-admin@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Attestor Review Admin",
                email_verified=True,
                totp_enabled=True,
                totp_secret=encrypt_totp_secret(secret),
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(
                    user_id=user.id,
                    role="admin",
                    approved_at=datetime.now(UTC),
                )
            )
        return user.id, secret


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


def application_payload() -> dict[str, object]:
    """Return a valid Attestor application request payload."""
    return {
        "specializations": ["healthcare", "governance"],
        "jurisdictions": ["US", "NG"],
        "credentials_summary": "Ten years auditing clinical operations.",
        "sample_work": {"reports": ["s3://example/private-sample.pdf"]},
        "professional_references": "Dr Ada Example, COO Example Health",
    }


async def test_user_submits_and_lists_own_attestor_application(
    client: AsyncClient,
    migrated_database: None,
    attestor_application_context: FakeRedis,
) -> None:
    """Authenticated users can submit and list their Attestor applications."""
    del migrated_database, attestor_application_context
    user_id = await create_user("attestor-candidate@auracles.space", ["operator"])

    submitted = await client.post(
        "/v1/attestor/applications",
        headers=auth_headers(user_id, ["operator"]),
        json=application_payload(),
    )
    mine = await client.get(
        "/v1/attestor/applications/mine",
        headers=auth_headers(user_id, ["operator"]),
    )

    assert submitted.status_code == 201
    assert submitted.json()["status"] == "pending"
    assert submitted.json()["user_id"] == str(user_id)
    assert submitted.json()["specializations"] == ["healthcare", "governance"]
    assert mine.status_code == 200
    assert [item["id"] for item in mine.json()["applications"]] == [
        submitted.json()["id"]
    ]

    async with async_session_factory() as session:
        application = await session.get(
            AttestorApplication,
            UUID(submitted.json()["id"]),
        )
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attestor_application_submitted"
            )
        )

    assert application is not None
    assert application.status == "pending"
    assert audit is not None


async def test_owner_edits_pending_application_in_place(
    client: AsyncClient,
    migrated_database: None,
    attestor_application_context: FakeRedis,
) -> None:
    """An owner can edit a pending application; edits are rejected once it is not.

    Editing updates the fields in place and keeps the application pending. After
    withdrawal the same application can no longer be edited (422).
    """
    del migrated_database, attestor_application_context
    user_id = await create_user("edit-candidate@auracles.space", ["operator"])
    headers = auth_headers(user_id, ["operator"])

    submitted = await client.post(
        "/v1/attestor/applications",
        headers=headers,
        json=application_payload(),
    )
    application_id = submitted.json()["id"]
    edited = await client.patch(
        f"/v1/attestor/applications/{application_id}",
        headers=headers,
        json={
            **application_payload(),
            "specializations": ["cybersecurity"],
            "credentials_summary": "Updated summary covering security audits.",
        },
    )
    await client.patch(
        f"/v1/attestor/applications/{application_id}/withdraw",
        headers=headers,
    )
    edit_after_withdraw = await client.patch(
        f"/v1/attestor/applications/{application_id}",
        headers=headers,
        json=application_payload(),
    )

    assert edited.status_code == 200
    assert edited.json()["status"] == "pending"
    assert edited.json()["specializations"] == ["cybersecurity"]
    assert edited.json()["credentials_summary"] == (
        "Updated summary covering security audits."
    )
    assert edit_after_withdraw.status_code == 422


async def test_user_cannot_edit_another_users_application(
    client: AsyncClient,
    migrated_database: None,
    attestor_application_context: FakeRedis,
) -> None:
    """Editing an application you do not own returns 404 (no disclosure)."""
    del migrated_database, attestor_application_context
    owner_id = await create_user("edit-owner@auracles.space", ["operator"])
    other_id = await create_user("edit-other@auracles.space", ["operator"])

    submitted = await client.post(
        "/v1/attestor/applications",
        headers=auth_headers(owner_id, ["operator"]),
        json=application_payload(),
    )
    forbidden = await client.patch(
        f"/v1/attestor/applications/{submitted.json()['id']}",
        headers=auth_headers(other_id, ["operator"]),
        json=application_payload(),
    )

    assert forbidden.status_code == 404


async def test_pending_application_can_be_withdrawn_and_then_reapplied(
    client: AsyncClient,
    migrated_database: None,
    attestor_application_context: FakeRedis,
) -> None:
    """Users can withdraw a pending application before submitting another one."""
    del migrated_database, attestor_application_context
    user_id = await create_user("withdraw-candidate@auracles.space", ["operator"])
    headers = auth_headers(user_id, ["operator"])

    first = await client.post(
        "/v1/attestor/applications",
        headers=headers,
        json=application_payload(),
    )
    duplicate = await client.post(
        "/v1/attestor/applications",
        headers=headers,
        json=application_payload(),
    )
    withdrawn = await client.patch(
        f"/v1/attestor/applications/{first.json()['id']}/withdraw",
        headers=headers,
    )
    second = await client.post(
        "/v1/attestor/applications",
        headers=headers,
        json=application_payload(),
    )

    async with async_session_factory() as session:
        withdrawn_row = await session.get(
            AttestorApplication,
            UUID(first.json()["id"]),
        )
        withdrawal_audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attestor_application_withdrawn"
            )
        )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "withdrawn"
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]
    assert withdrawn_row is not None
    assert withdrawn_row.status == "withdrawn"
    assert withdrawal_audit is not None


async def test_admin_approves_attestor_application_with_profile_and_role(
    client: AsyncClient,
    migrated_database: None,
    attestor_application_context: FakeRedis,
) -> None:
    """Admin approval creates the matcher profile and approves Attestor role."""
    del migrated_database, attestor_application_context
    candidate_id = await create_user("approved-attestor@auracles.space", ["operator"])
    admin_id, totp_secret = await create_admin_user()
    submitted = await client.post(
        "/v1/attestor/applications",
        headers=auth_headers(candidate_id, ["operator"]),
        json=application_payload(),
    )

    listed = await client.get(
        "/v1/admin/attestor/applications?status=pending",
        headers=auth_headers(admin_id, ["admin"]),
    )
    approved = await client.post(
        f"/v1/admin/attestor/applications/{submitted.json()['id']}/review",
        headers=auth_headers(admin_id, ["admin"]),
        json={
            "decision": "approved",
            "feedback": "Credential set is strong enough for the launch cohort.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
        },
    )

    async with async_session_factory() as session:
        profile = await session.scalar(
            select(AttestorProfile).where(AttestorProfile.user_id == candidate_id)
        )
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == candidate_id,
                UserRole.role == "attestor",
            )
        )
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attestor_application_approved"
            )
        )

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["applications"]] == [
        submitted.json()["id"]
    ]
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["reviewed_by"] == str(admin_id)
    assert profile is not None
    assert profile.active is True
    assert profile.specializations == ["healthcare", "governance"]
    assert role is not None
    assert role.approved_at is not None
    assert role.approved_by == admin_id
    assert audit is not None


async def test_admin_rejects_attestor_application_with_feedback(
    client: AsyncClient,
    migrated_database: None,
    attestor_application_context: FakeRedis,
) -> None:
    """Admin rejection stores feedback but does not approve Attestor access."""
    del migrated_database, attestor_application_context
    candidate_id = await create_user("rejected-attestor@auracles.space", ["operator"])
    admin_id, totp_secret = await create_admin_user()
    submitted = await client.post(
        "/v1/attestor/applications",
        headers=auth_headers(candidate_id, ["operator"]),
        json=application_payload(),
    )

    missing_feedback = await client.post(
        f"/v1/admin/attestor/applications/{submitted.json()['id']}/review",
        headers=auth_headers(admin_id, ["admin"]),
        json={
            "decision": "rejected",
            "totp_code": pyotp.TOTP(totp_secret).now(),
        },
    )
    rejected = await client.post(
        f"/v1/admin/attestor/applications/{submitted.json()['id']}/review",
        headers=auth_headers(admin_id, ["admin"]),
        json={
            "decision": "rejected",
            "feedback": "Please add verifiable client references.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
        },
    )

    async with async_session_factory() as session:
        profile = await session.scalar(
            select(AttestorProfile).where(AttestorProfile.user_id == candidate_id)
        )
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == candidate_id,
                UserRole.role == "attestor",
            )
        )
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attestor_application_rejected"
            )
        )

    assert missing_feedback.status_code == 422
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert (
        rejected.json()["admin_feedback"]
        == "Please add verifiable client references."
    )
    assert rejected.json()["reviewed_by"] == str(admin_id)
    assert profile is None
    assert role is None
    assert audit is not None
