"""Integration tests for organization business verification (KYB).

KYB establishes an org's legal identity once and gates every capability, so
these cover the guards that make the gate meaningful: an unverified org cannot
activate anything, a verified identity cannot be quietly edited, and an admin
cannot certify documents that were never uploaded.

Maps to: DESIGN-1.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgLegalProfile,
    OrgMember,
)
from app.shared.models.audit_log import AuditLog
from tests.integration.test_auth_sessions import FakeRedis

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the integration database is upgraded to alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database: None) -> AsyncIterator[FakeRedis]:
    """Reset org rows between tests and install a fake Redis."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in FK-safe order."""
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(delete(AuditLog))
                await session.execute(delete(OrgLegalProfile))
                await session.execute(delete(OrgCapability))
                await session.execute(delete(OrgMember))
                await session.execute(delete(Organization))
                await session.execute(delete(UserRole))
                await session.execute(delete(User))

    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    await cleanup()
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


def _auth(user_id: UUID, roles: list[str] | None = None) -> dict[str, str]:
    """Build a bearer Authorization header for one user."""
    return {
        "Authorization": f"Bearer {create_access_token(user_id, roles or [])}"
    }


async def _user(prefix: str, *, totp_secret: str | None = None) -> UUID:
    """Create a verified user, optionally TOTP-enabled."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
                totp_enabled=totp_secret is not None,
                totp_secret=(
                    encrypt_totp_secret(totp_secret) if totp_secret else None
                ),
            )
            session.add(user)
            await session.flush()
            return user.id


async def _org(owner_id: UUID, *, country: str = "NG") -> UUID:
    """Create an organization owned by one user."""
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"kyb-{uuid4().hex[:6]}",
                name="Kyb Test Org",
                country=country,
                created_by=owner_id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner_id, role="owner"))
            return org.id


async def _profile(
    org_id: UUID,
    *,
    kyb_status: str = "unverified",
    registration_number: str | None = "RC123456",
    doc_keys: list[str] | None = None,
) -> None:
    """Seed the org's legal profile in a given verification state."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgLegalProfile(
                    org_id=org_id,
                    legal_name="Kyb Test Org Ltd",
                    registration_number=registration_number,
                    incorporation_doc_keys=doc_keys
                    if doc_keys is not None
                    else ["org-incorporation-docs/seed/cert.pdf"],
                    kyb_status=kyb_status,
                    kyb_verified_at=(
                        datetime.now(UTC) if kyb_status == "verified" else None
                    ),
                )
            )


async def test_unverified_org_cannot_activate_a_capability(
    client: AsyncClient, clean_state: FakeRedis
) -> None:
    """Capabilities stay shut until the organization is business-verified.

    This is the whole point of the gate: before it, Contributor and Operator
    self-activated instantly with no identity check at all.
    """
    del clean_state
    owner_id = await _user("owner")
    org_id = await _org(owner_id)

    res = await client.post(
        f"/v1/orgs/{org_id}/contributor-capability/activate",
        headers=_auth(owner_id),
    )

    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "org_kyb_required"

    async with async_session_factory() as session:
        capability = await session.scalar(
            select(OrgCapability).where(OrgCapability.org_id == org_id)
        )
    assert capability is None


async def test_verified_org_can_activate_a_capability(
    client: AsyncClient, clean_state: FakeRedis
) -> None:
    """Verification is the only thing standing between an org and activation."""
    del clean_state
    owner_id = await _user("owner")
    org_id = await _org(owner_id)
    await _profile(org_id, kyb_status="verified")

    res = await client.post(
        f"/v1/orgs/{org_id}/operator-capability/activate",
        headers=_auth(owner_id),
    )

    assert res.status_code == 200
    assert res.json()["status"] == "active"


async def test_submit_requires_a_registration_number_and_document(
    client: AsyncClient, clean_state: FakeRedis
) -> None:
    """An admin should never be handed an empty application to judge."""
    del clean_state
    owner_id = await _user("owner")
    org_id = await _org(owner_id)
    await _profile(org_id, registration_number=None, doc_keys=[])

    res = await client.post(f"/v1/orgs/{org_id}/kyb/submit", headers=_auth(owner_id))

    assert res.status_code == 422


async def test_verified_identity_cannot_be_edited(
    client: AsyncClient, clean_state: FakeRedis
) -> None:
    """A verified org cannot drop the documents it was verified against.

    Without this the badge survives a change of identity, which on a platform
    selling provenance is worse than having no badge.
    """
    del clean_state
    owner_id = await _user("owner")
    org_id = await _org(owner_id)
    await _profile(org_id, kyb_status="verified")

    res = await client.request(
        "DELETE",
        f"/v1/orgs/{org_id}/kyb/incorporation-document",
        json={"s3_key": "org-incorporation-docs/seed/cert.pdf"},
        headers=_auth(owner_id),
    )

    assert res.status_code == 409


async def test_admin_rejection_requires_a_reason_and_is_not_terminal(
    client: AsyncClient, clean_state: FakeRedis
) -> None:
    """A rejected org learns why and may fix it and resubmit."""
    del clean_state
    owner_id = await _user("owner")
    admin_secret = pyotp.random_base32()
    admin_id = await _user("admin", totp_secret=admin_secret)
    org_id = await _org(owner_id)
    await _profile(org_id, kyb_status="pending")
    review_path = f"/v1/admin/orgs/{org_id}/kyb/review"

    silent = await client.post(
        review_path,
        json={"verdict": "rejected", "totp_code": pyotp.TOTP(admin_secret).now()},
        headers=_auth(admin_id, ["admin"]),
    )
    assert silent.status_code == 422

    rejected = await client.post(
        review_path,
        json={
            "verdict": "rejected",
            "notes": "The certificate is unreadable.",
            "totp_code": pyotp.TOTP(admin_secret).at(
                datetime.now(UTC).timestamp() + 30
            ),
        },
        headers=_auth(admin_id, ["admin"]),
    )
    assert rejected.status_code == 200
    assert rejected.json()["kyb_status"] == "rejected"
    assert rejected.json()["kyb_review_notes"] == "The certificate is unreadable."

    # Not terminal: the org corrects course and submits again.
    resubmitted = await client.post(
        f"/v1/orgs/{org_id}/kyb/submit", headers=_auth(owner_id)
    )
    assert resubmitted.status_code == 200
    assert resubmitted.json()["kyb_status"] == "pending"


async def test_admin_cannot_verify_documents_that_were_never_uploaded(
    client: AsyncClient, clean_state: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key is reserved before the browser uploads, so absence is possible.

    Certifying against a document nobody could read would make the verdict
    meaningless.
    """
    del clean_state
    from app.integrations import s3

    monkeypatch.setattr(s3.storage, "object_exists", lambda bucket, key: False)
    owner_id = await _user("owner")
    admin_secret = pyotp.random_base32()
    admin_id = await _user("admin", totp_secret=admin_secret)
    org_id = await _org(owner_id)
    await _profile(org_id, kyb_status="pending")

    res = await client.post(
        f"/v1/admin/orgs/{org_id}/kyb/review",
        json={"verdict": "verified", "totp_code": pyotp.TOTP(admin_secret).now()},
        headers=_auth(admin_id, ["admin"]),
    )

    assert res.status_code == 422
    assert "never uploaded" in res.json()["detail"]
