"""Integration tests for Organizations Core org CRUD endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import User
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgMember,
)
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure application tables exist."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


async def _reset_org_state() -> None:
    """Delete org rows and identity rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(OrgCapability))
        await session.execute(delete(OrgMember))
        await session.execute(delete(Organization))
        await clear_identity_state_async(session)
        await session.commit()


@pytest.fixture
async def clean_orgs() -> AsyncIterator[None]:
    """Reset org state before and after each test.

    The teardown matters: organizations.created_by references users, so
    leftover org rows break the `delete(User)` cleanup other test files
    rely on.
    """
    await engine.dispose()
    await _reset_org_state()
    try:
        yield
    finally:
        await _reset_org_state()
        await engine.dispose()


async def create_user(prefix: str) -> UUID:
    """Create a verified user with a unique email; return its id."""
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
            return user.id


def auth(token: str) -> dict[str, str]:
    """Build an Authorization header."""
    return {"Authorization": f"Bearer {token}"}


async def create_org(client: AsyncClient, token: str, prefix: str) -> dict[str, object]:
    """Create an org via the API; return the response body."""
    response = await client.post(
        "/v1/orgs",
        json={"slug": f"{prefix}-{uuid4().hex[:6]}", "name": prefix, "country": "GB"},
        headers=auth(token),
    )
    assert response.status_code == 201
    return dict(response.json())


async def add_member(org_id: str, user_id: UUID, role: str) -> UUID:
    """Insert a membership row directly and return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=UUID(org_id), user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            return member.id


async def test_create_org_seeds_owner_membership(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """POST /v1/orgs creates the org and seeds the creator as owner."""
    del migrated_database, clean_orgs
    user_id = await create_user("org-create")
    token = create_access_token(user_id, [])
    slug = f"acme-{uuid4().hex[:6]}"

    response = await client.post(
        "/v1/orgs",
        json={"slug": slug, "name": "Acme Compliance", "country": "GB"},
        headers=auth(token),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == slug
    async with async_session_factory() as session:
        member = await session.scalar(
            select(OrgMember).where(
                OrgMember.org_id == UUID(body["id"]),
                OrgMember.user_id == user_id,
            )
        )
    assert member is not None and member.role == "owner"


async def test_create_org_duplicate_slug_conflicts(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """Reusing a slug returns 409."""
    del migrated_database, clean_orgs
    user_id = await create_user("org-dup")
    token = create_access_token(user_id, [])
    slug = f"dup-{uuid4().hex[:6]}"

    first = await client.post(
        "/v1/orgs",
        json={"slug": slug, "name": "First", "country": "GB"},
        headers=auth(token),
    )
    assert first.status_code == 201

    second = await client.post(
        "/v1/orgs",
        json={"slug": slug.upper(), "name": "Second", "country": "GB"},
        headers=auth(token),
    )

    assert second.status_code == 409


async def test_create_org_requires_auth(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """Unauthenticated create returns 401."""
    del migrated_database, clean_orgs
    response = await client.post(
        "/v1/orgs",
        json={"slug": "nope", "name": "Nope", "country": "GB"},
    )
    assert response.status_code == 401


async def test_list_my_orgs_returns_role_and_capabilities(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """GET /v1/orgs/mine lists my orgs with role and capability statuses."""
    del migrated_database, clean_orgs
    user_id = await create_user("org-mine")
    token = create_access_token(user_id, [])
    created = await client.post(
        "/v1/orgs",
        json={"slug": f"mine-{uuid4().hex[:6]}", "name": "Mine", "country": "NG"},
        headers=auth(token),
    )
    org_id = UUID(created.json()["id"])
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(org_id=org_id, capability="attestor", status="pending")
            )

    response = await client.get("/v1/orgs/mine", headers=auth(token))

    assert response.status_code == 200
    orgs = response.json()["organizations"]
    assert len(orgs) == 1
    assert orgs[0]["role"] == "owner"
    assert orgs[0]["capabilities"] == {"attestor": "pending"}


async def test_list_my_orgs_excludes_deactivated(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """GET /v1/orgs/mine omits organizations that have been deactivated."""
    del migrated_database, clean_orgs
    user_id = await create_user("org-mine-deact")
    token = create_access_token(user_id, [])
    org = await create_org(client, token, "gone")
    deleted = await client.delete(f"/v1/orgs/{org['id']}", headers=auth(token))
    assert deleted.status_code == 204

    response = await client.get("/v1/orgs/mine", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["organizations"] == []


async def test_public_org_profile_exposes_no_members(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """GET /v1/orgs/{slug} is public and returns no member PII."""
    del migrated_database, clean_orgs
    user_id = await create_user("org-public")
    token = create_access_token(user_id, [])
    org = await create_org(client, token, "pub")

    response = await client.get(f"/v1/orgs/{org['slug']}")

    assert response.status_code == 200
    body = response.json()
    assert body["member_count"] == 1
    assert body["active_capabilities"] == []
    assert "members" not in body and "email" not in str(body)


async def test_update_org_requires_admin(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """PATCH /v1/orgs/{org_id} is admin+; a plain member gets 403."""
    del migrated_database, clean_orgs
    owner_id = await create_user("org-upd-owner")
    member_id = await create_user("org-upd-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "upd")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgMember(org_id=UUID(str(org["id"])), user_id=member_id, role="member")
            )

    member_token = create_access_token(member_id, [])
    denied = await client.patch(
        f"/v1/orgs/{org['id']}",
        json={"name": "New"},
        headers=auth(member_token),
    )
    allowed = await client.patch(
        f"/v1/orgs/{org['id']}",
        json={"name": "New"},
        headers=auth(owner_token),
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["name"] == "New"


async def test_suspended_org_denial_is_audited(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """A 403 on a suspended org writes an access_denied audit row.

    Enforces the spec rule that all org RBAC denials are audited,
    including denials caused by platform suspension.
    """
    del migrated_database, clean_orgs
    owner_id = await create_user("org-susp")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "susp")
    org_id = UUID(str(org["id"]))
    async with async_session_factory() as session:
        async with session.begin():
            organization = await session.get(Organization, org_id)
            assert organization is not None
            organization.suspended_at = datetime.now(UTC)

    response = await client.patch(
        f"/v1/orgs/{org_id}",
        json={"name": "Blocked"},
        headers=auth(token),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "org_suspended"
    async with async_session_factory() as session:
        audit_row = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "access_denied",
                AuditLog.target_type == "org_rbac",
                AuditLog.target_id == org_id,
            )
        )
    assert audit_row is not None


async def test_deactivate_blocked_while_capability_active(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """DELETE /v1/orgs/{org_id} returns 409 while any capability is active."""
    del migrated_database, clean_orgs
    owner_id = await create_user("org-deact")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "deact")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=UUID(str(org["id"])),
                    capability="attestor",
                    status="active",
                )
            )

    blocked = await client.delete(f"/v1/orgs/{org['id']}", headers=auth(token))

    assert blocked.status_code == 409


async def test_deactivate_owner_only(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """DELETE /v1/orgs/{org_id} requires the owner role; admin gets 403."""
    del migrated_database, clean_orgs
    owner_id = await create_user("org-deact-owner")
    admin_id = await create_user("org-deact-admin")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "downer")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgMember(org_id=UUID(str(org["id"])), user_id=admin_id, role="admin")
            )

    denied = await client.delete(
        f"/v1/orgs/{org['id']}",
        headers=auth(create_access_token(admin_id, [])),
    )
    allowed = await client.delete(f"/v1/orgs/{org['id']}", headers=auth(owner_token))

    assert denied.status_code == 403
    assert allowed.status_code == 204


async def test_member_list_hides_emails_from_plain_members(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """GET members shows emails to admin+ callers only."""
    del migrated_database, clean_orgs
    owner_id = await create_user("mem-owner")
    member_id = await create_user("mem-plain")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "mem")
    await add_member(str(org["id"]), member_id, "member")

    as_owner = await client.get(
        f"/v1/orgs/{org['id']}/members",
        headers=auth(owner_token),
    )
    as_member = await client.get(
        f"/v1/orgs/{org['id']}/members",
        headers=auth(create_access_token(member_id, [])),
    )

    assert as_owner.status_code == 200
    assert as_member.status_code == 200
    assert all(member["email"] for member in as_owner.json()["members"])
    assert all(member["email"] is None for member in as_member.json()["members"])


async def test_owner_cannot_be_removed(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """Removing the owner returns 409."""
    del migrated_database, clean_orgs
    owner_id = await create_user("rm-owner")
    admin_id = await create_user("rm-admin")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "rmo")
    await add_member(str(org["id"]), admin_id, "admin")
    async with async_session_factory() as session:
        owner_member = await session.scalar(
            select(OrgMember).where(
                OrgMember.org_id == UUID(str(org["id"])),
                OrgMember.role == "owner",
            )
        )

    assert owner_member is not None
    response = await client.delete(
        f"/v1/orgs/{org['id']}/members/{owner_member.id}",
        headers=auth(create_access_token(admin_id, [])),
    )

    assert response.status_code == 409


async def test_admin_cannot_remove_admin_but_owner_can(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """Admin removing another admin is forbidden; owner removal succeeds."""
    del migrated_database, clean_orgs
    owner_id = await create_user("rm2-owner")
    admin_a = await create_user("rm2-admin-a")
    admin_b = await create_user("rm2-admin-b")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "rm2")
    await add_member(str(org["id"]), admin_a, "admin")
    target = await add_member(str(org["id"]), admin_b, "admin")

    denied = await client.delete(
        f"/v1/orgs/{org['id']}/members/{target}",
        headers=auth(create_access_token(admin_a, [])),
    )
    allowed = await client.delete(
        f"/v1/orgs/{org['id']}/members/{target}",
        headers=auth(owner_token),
    )

    assert denied.status_code == 403
    assert allowed.status_code == 204


async def test_member_can_leave(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """Self-removal is allowed for non-owner members."""
    del migrated_database, clean_orgs
    owner_id = await create_user("leave-owner")
    member_id = await create_user("leave-member")
    org = await create_org(client, create_access_token(owner_id, []), "leave")
    member_row = await add_member(str(org["id"]), member_id, "member")

    response = await client.delete(
        f"/v1/orgs/{org['id']}/members/{member_row}",
        headers=auth(create_access_token(member_id, [])),
    )

    assert response.status_code == 204


async def test_role_change_owner_only_and_never_to_owner(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """Owner can promote member to admin; role cannot be changed to owner here."""
    del migrated_database, clean_orgs
    owner_id = await create_user("role-owner")
    member_id = await create_user("role-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "role")
    member_row = await add_member(str(org["id"]), member_id, "member")

    promoted = await client.patch(
        f"/v1/orgs/{org['id']}/members/{member_row}",
        json={"role": "admin"},
        headers=auth(owner_token),
    )
    to_owner = await client.patch(
        f"/v1/orgs/{org['id']}/members/{member_row}",
        json={"role": "owner"},
        headers=auth(owner_token),
    )

    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"
    assert to_owner.status_code == 422


async def test_ownership_transfer_requires_totp(
    client: AsyncClient, migrated_database: None, clean_orgs: None
) -> None:
    """Ownership transfer is blocked until the owner enables 2FA."""
    del migrated_database, clean_orgs
    owner_id = await create_user("xfer-owner")
    member_id = await create_user("xfer-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "xfer")
    member_row = await add_member(str(org["id"]), member_id, "member")

    response = await client.post(
        f"/v1/orgs/{org['id']}/transfer-ownership",
        json={"new_owner_member_id": str(member_row), "totp_code": "000000"},
        headers=auth(owner_token),
    )

    assert response.status_code == 403


async def test_ownership_transfer_swaps_roles(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verified transfer demotes the old owner and promotes the new one."""
    del migrated_database, clean_orgs
    from app.modules.organizations import service as org_service

    async def totp_ok(*args: object, **kwargs: object) -> None:
        """Accept the transfer without real TOTP setup in this test."""
        del args, kwargs

    monkeypatch.setattr(org_service, "verify_totp_for_sensitive_action", totp_ok)
    owner_id = await create_user("xfer2-owner")
    member_id = await create_user("xfer2-member")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "xfer2")
    member_row = await add_member(str(org["id"]), member_id, "admin")

    response = await client.post(
        f"/v1/orgs/{org['id']}/transfer-ownership",
        json={"new_owner_member_id": str(member_row), "totp_code": "123456"},
        headers=auth(owner_token),
    )

    assert response.status_code == 204
    async with async_session_factory() as session:
        memberships = (
            await session.scalars(
                select(OrgMember).where(OrgMember.org_id == UUID(str(org["id"])))
            )
        ).all()

    roles = {membership.user_id: membership.role for membership in memberships}
    assert roles[member_id] == "owner"
    assert roles[owner_id] == "admin"
