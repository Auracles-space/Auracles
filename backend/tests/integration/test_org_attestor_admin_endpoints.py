"""Integration tests for the platform-admin org attestor review endpoints.

Covers the review queue and gate-walk routes under
/v1/admin/org-attestor-applications plus the capability suspend/reinstate/
revoke routes under /v1/admin/orgs, including RBAC (401/403) and the full
submit → verify-kyb → ... → approve walk.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.attestation.models import AttestorTrial
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import PayoutAccount
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgAttestorProfile,
    OrgCapability,
    OrgMember,
    OrgMemberNda,
)
from app.shared.models.audit_log import AuditLog
from tests.integration.test_auth_sessions import FakeRedis

pytestmark = pytest.mark.asyncio

_QUEUE = "/v1/admin/org-attestor-applications"


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure application tables exist."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def clean_state() -> AsyncIterator[FakeRedis]:
    """Reset org attestor rows between tests; install fake Redis."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in FK order between tests."""
        async with async_session_factory() as session:
            await session.execute(delete(AttestorTrial))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgAttestorApplication))
            await session.execute(delete(OrgMemberNda))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(PayoutAccount))
            await session.execute(delete(Organization))
            await session.execute(delete(UserRole))
            await session.execute(delete(AuditLog))
            await session.commit()

    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    await cleanup()
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()


def auth(user_id: UUID, roles: list[str] | None = None) -> dict[str, str]:
    """Build an Authorization header for the given user (with token roles)."""
    return {"Authorization": f"Bearer {create_access_token(user_id, roles or [])}"}


async def _new_user(prefix: str, *, roles: list[str] | None = None) -> UUID:
    """Create a verified user with optional platform roles; return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            for role in roles or []:
                session.add(UserRole(user_id=user.id, role=role))
            return user.id


async def _org(owner_id: UUID) -> UUID:
    """Create org + owner member + pending attestor capability; return org id."""
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"adm-{uuid4().hex[:6]}",
                name="Admin Endpoint Org",
                country="US",
                created_by=owner_id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner_id, role="owner"))
            session.add(
                OrgCapability(org_id=org.id, capability="attestor", status="pending")
            )
            return org.id


async def _gated_application(org_id: UUID, owner_id: UUID) -> UUID:
    """Create a submitted application with all gates satisfied; return its id."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            member = await session.scalar(
                select(OrgMember).where(
                    OrgMember.org_id == org_id, OrgMember.user_id == owner_id
                )
            )
            assert member is not None
            account = PayoutAccount(
                org_id=org_id,
                provider="stripe",
                provider_account_id=f"acct_{uuid4().hex[:12]}",
                provider_account_lookup_hash=uuid4().hex + uuid4().hex,
                account_type="express",
            )
            session.add(account)
            await session.flush()
            application = OrgAttestorApplication(
                org_id=org_id,
                status="submitted",
                specializations=[],
                legal_name="Acme Attestations Ltd",
                registration_number="RC123456",
                incorporation_doc_keys=["kyb/acme/cert.pdf"],
                sectors=["PE"],
                framework_categories=["Compliance"],
                jurisdictions=["US"],
                credentials_summary="Two decades of PE compliance experience.",
                sample_work={},
                professional_references="Jane Roe, MD.",
                kyb_verified_at=now,
                coi_declarations=[],
                coi_signed_at=now,
                coi_expires_at=now,
                confidentiality_signed_at=now,
                payout_account_id=account.id,
                tax_document_type="w9",
                tax_document_key="org-tax/key.pdf",
                trial_member_id=member.id,
            )
            session.add(application)
            await session.flush()
            session.add(
                AttestorTrial(
                    org_application_id=application.id,
                    org_id=org_id,
                    member_id=member.id,
                    status="passed",
                )
            )
            return application.id


async def test_queue_requires_admin(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """The queue rejects anonymous (401) and non-admin (403) callers."""
    plain_id = await _new_user("plain")
    assert (await client.get(_QUEUE)).status_code == 401
    assert (await client.get(_QUEUE, headers=auth(plain_id))).status_code == 403


async def test_queue_lists_and_filters(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """An admin lists the queue and filters it by status."""
    admin_id = await _new_user("admin", roles=["admin"])
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    await _gated_application(org_id, owner_id)

    res = await client.get(_QUEUE, headers=auth(admin_id, ["admin"]))
    assert res.status_code == 200
    assert res.json()["total"] == 1

    filtered = await client.get(
        f"{_QUEUE}?status=needs_info", headers=auth(admin_id, ["admin"])
    )
    assert filtered.json()["total"] == 0


async def test_full_gate_walk_to_approval(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Verify-kyb → start-trial → approve activates the capability."""
    admin_id = await _new_user("admin", roles=["admin"])
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    application_id = await _gated_application(org_id, owner_id)

    verified = await client.post(
        f"{_QUEUE}/{application_id}/verify-kyb", headers=auth(admin_id, ["admin"])
    )
    assert verified.status_code == 200
    assert verified.json()["gate_checklist"]["kyb_verified"] is True

    trial = await client.post(
        f"{_QUEUE}/{application_id}/start-trial", headers=auth(admin_id, ["admin"])
    )
    assert trial.status_code == 200

    approved = await client.post(
        f"{_QUEUE}/{application_id}/approve", headers=auth(admin_id, ["admin"])
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    async with async_session_factory() as session:
        capability = await session.scalar(
            select(OrgCapability).where(
                OrgCapability.org_id == org_id,
                OrgCapability.capability == "attestor",
            )
        )
        assert capability is not None and capability.status == "active"
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == owner_id, UserRole.role == "attestor"
            )
        )
        assert role is not None


async def test_needs_info_and_reject(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Needs-info transitions the application; reject terminates it."""
    admin_id = await _new_user("admin", roles=["admin"])
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    application_id = await _gated_application(org_id, owner_id)

    held = await client.post(
        f"{_QUEUE}/{application_id}/needs-info",
        json={"feedback": "Clarify jurisdictions."},
        headers=auth(admin_id, ["admin"]),
    )
    assert held.status_code == 200
    assert held.json()["status"] == "needs_info"

    rejected = await client.post(
        f"{_QUEUE}/{application_id}/reject",
        json={"feedback": "Not a fit at this time."},
        headers=auth(admin_id, ["admin"]),
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


async def test_capability_suspend_reinstate_revoke(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Suspend/reinstate/revoke drive the derived role and profile state."""
    admin_id = await _new_user("admin", roles=["admin"])
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    application_id = await _gated_application(org_id, owner_id)
    await client.post(
        f"{_QUEUE}/{application_id}/approve", headers=auth(admin_id, ["admin"])
    )

    base = f"/v1/admin/orgs/{org_id}/attestor-capability"
    assert (
        await client.post(f"{base}/suspend", headers=auth(admin_id, ["admin"]))
    ).status_code == 204

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == owner_id, UserRole.role == "attestor"
            )
        )
        assert role is None

    assert (
        await client.post(f"{base}/reinstate", headers=auth(admin_id, ["admin"]))
    ).status_code == 204
    assert (
        await client.post(f"{base}/revoke", headers=auth(admin_id, ["admin"]))
    ).status_code == 204

    async with async_session_factory() as session:
        profile = await session.scalar(
            select(OrgAttestorProfile).where(OrgAttestorProfile.org_id == org_id)
        )
        assert profile is not None and profile.active is False


async def test_capability_routes_require_admin(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Capability routes reject anonymous (401) and non-admin (403) callers."""
    plain_id = await _new_user("plain")
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    base = f"/v1/admin/orgs/{org_id}/attestor-capability/suspend"
    assert (await client.post(base)).status_code == 401
    assert (await client.post(base, headers=auth(plain_id))).status_code == 403
