"""Integration tests for org member NDA endpoints.

Covers GET /v1/orgs/{org_id}/nda and POST /v1/orgs/{org_id}/nda/sign
plus the nda_required signal on invitation acceptance.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password, hash_token
from app.main import app
from app.modules.auth.models import User
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgInvitation,
    OrgMember,
    OrgMemberNda,
)
from app.shared.models.audit_log import AuditLog
from tests.integration.test_auth_sessions import FakeRedis

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure application tables exist."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def clean_nda_state() -> AsyncIterator[FakeRedis]:
    """Remove NDA and org rows between tests; install fake Redis."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete NDA/org rows between tests."""
        async with async_session_factory() as session:
            await session.execute(delete(OrgMemberNda))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgInvitation))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
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


async def create_user(prefix: str) -> tuple[UUID, str]:
    """Create a verified user; return (id, email)."""
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
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
            return user.id, email


def auth(user_id: UUID) -> dict[str, str]:
    """Build an Authorization header for the given user."""
    return {"Authorization": f"Bearer {create_access_token(user_id, [])}"}


async def create_org_with_capability(
    owner_id: UUID,
    *,
    attestor_status: str | None = "pending",
) -> str:
    """Insert org + owner member (+ attestor capability); return org id."""
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"nda-org-{uuid4().hex[:6]}",
                name="NDA Endpoint Org",
                country="US",
                created_by=owner_id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner_id, role="owner"))
            if attestor_status is not None:
                session.add(
                    OrgCapability(
                        org_id=org.id,
                        capability="attestor",
                        status=attestor_status,
                    )
                )
            return str(org.id)


async def test_nda_status_and_sign_happy_path(
    client: AsyncClient, migrated_database: None, clean_nda_state: None
) -> None:
    """Member reads required status, signs, then reads the signature back."""
    owner_id, _ = await create_user("nda-owner")
    org_id = await create_org_with_capability(owner_id)

    status_res = await client.get(f"/v1/orgs/{org_id}/nda", headers=auth(owner_id))
    assert status_res.status_code == 200
    body = status_res.json()
    assert body["required"] is True
    assert body["signed_version"] is None

    sign_res = await client.post(
        f"/v1/orgs/{org_id}/nda/sign", headers=auth(owner_id)
    )
    assert sign_res.status_code == 200
    signed = sign_res.json()
    assert signed["signed_version"] == body["current_version"]
    assert signed["signed_at"] is not None

    again = await client.get(f"/v1/orgs/{org_id}/nda", headers=auth(owner_id))
    assert again.json()["signed_version"] == body["current_version"]


async def test_nda_requires_authentication(
    client: AsyncClient, migrated_database: None, clean_nda_state: None
) -> None:
    """Unauthenticated NDA reads and signs return 401."""
    owner_id, _ = await create_user("nda-anon")
    org_id = await create_org_with_capability(owner_id)
    assert (await client.get(f"/v1/orgs/{org_id}/nda")).status_code == 401
    assert (await client.post(f"/v1/orgs/{org_id}/nda/sign")).status_code == 401


async def test_nda_rejects_non_member(
    client: AsyncClient, migrated_database: None, clean_nda_state: None
) -> None:
    """A user outside the org gets 403 from both NDA endpoints."""
    owner_id, _ = await create_user("nda-own")
    outsider_id, _ = await create_user("nda-out")
    org_id = await create_org_with_capability(owner_id)
    assert (
        await client.get(f"/v1/orgs/{org_id}/nda", headers=auth(outsider_id))
    ).status_code == 403
    assert (
        await client.post(f"/v1/orgs/{org_id}/nda/sign", headers=auth(outsider_id))
    ).status_code == 403


async def test_nda_sign_rate_limited(
    client: AsyncClient, migrated_database: None, clean_nda_state: FakeRedis
) -> None:
    """A sign attempt past the per-user window limit returns 429."""
    owner_id, _ = await create_user("nda-rate")
    org_id = await create_org_with_capability(owner_id)
    first = await client.post(f"/v1/orgs/{org_id}/nda/sign", headers=auth(owner_id))
    assert first.status_code == 200

    clean_nda_state.counters[f"rate_limit:org_nda_sign:{owner_id}"] = 5
    limited = await client.post(
        f"/v1/orgs/{org_id}/nda/sign", headers=auth(owner_id)
    )
    assert limited.status_code == 429


async def test_accept_invitation_reports_nda_required(
    client: AsyncClient, migrated_database: None, clean_nda_state: None
) -> None:
    """Invitation acceptance carries nda_required for attestor orgs."""
    owner_id, _ = await create_user("nda-inviter")
    invitee_id, invitee_email = await create_user("nda-invitee")
    org_id = await create_org_with_capability(owner_id, attestor_status="active")

    token = uuid4().hex
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgInvitation(
                    org_id=UUID(org_id),
                    email=invitee_email.lower(),
                    role="member",
                    invited_by=owner_id,
                    status="pending",
                    token_hash=hash_token(token),
                    expires_at=datetime.now(UTC) + timedelta(days=7),
                )
            )

    res = await client.post(
        f"/v1/org-invitations/{token}/accept", headers=auth(invitee_id)
    )
    assert res.status_code == 200
    assert res.json()["nda_required"] is True


async def test_accept_invitation_without_capability_not_required(
    client: AsyncClient, migrated_database: None, clean_nda_state: None
) -> None:
    """Acceptance into an org without attestor capability reports False."""
    owner_id, _ = await create_user("nda-plain")
    invitee_id, invitee_email = await create_user("nda-plain-inv")
    org_id = await create_org_with_capability(owner_id, attestor_status=None)

    token = uuid4().hex
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgInvitation(
                    org_id=UUID(org_id),
                    email=invitee_email.lower(),
                    role="member",
                    invited_by=owner_id,
                    status="pending",
                    token_hash=hash_token(token),
                    expires_at=datetime.now(UTC) + timedelta(days=7),
                )
            )

    res = await client.post(
        f"/v1/org-invitations/{token}/accept", headers=auth(invitee_id)
    )
    assert res.status_code == 200
    assert res.json()["nda_required"] is False
