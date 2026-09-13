"""Integration tests for individual-attestor pipeline retirement.

The individual attestor onboarding pipeline (self-service applications, admin
KYC/credential/trial/activation gates) is retired: its endpoints are gone and
return 404. The attestor role is granted only as a derived role through an
organization's active attestor capability. User-owned credential endpoints are
unrelated and survive. Enforces the retirement step of
docs/superpowers/specs/2026-07-04-org-attestor-design.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import User
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the schema is upgraded to head."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def clean_state(migrated_database: None) -> AsyncIterator[None]:
    """Reset the small set of rows these tests create."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(delete(AuditLog))
                await session.execute(delete(User))

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


def _auth(user_id: UUID, roles: list[str] | None = None) -> dict[str, str]:
    """Build an Authorization header for one user."""
    return {"Authorization": f"Bearer {create_access_token(user_id, roles or [])}"}


async def _new_user() -> UUID:
    """Create one verified user; return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"u-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="user",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            return user.id


async def test_individual_attestor_application_endpoints_removed(
    client: AsyncClient, clean_state: None
) -> None:
    """The retired self-service application endpoints return 404."""
    del clean_state
    user_id = await _new_user()

    create = await client.post(
        "/v1/attestor/applications",
        json={
            "legal_name": "Solo Attestor",
            "sectors": ["private_equity"],
            "functions": ["compliance"],
            "jurisdictions": ["united_states"],
            "credentials_summary": "Two decades of experience.",
            "professional_references": "Jane Roe.",
        },
        headers=_auth(user_id),
    )
    assert create.status_code == 404

    mine = await client.get("/v1/attestor/applications/mine", headers=_auth(user_id))
    assert mine.status_code == 404


async def test_individual_attestor_admin_endpoints_removed(
    client: AsyncClient, clean_state: None
) -> None:
    """The retired admin gate-walk endpoints return 404."""
    del clean_state
    admin_id = await _new_user()
    application_id = uuid4()

    queue = await client.get(
        "/v1/admin/attestor/applications", headers=_auth(admin_id, ["admin"])
    )
    assert queue.status_code == 404

    activate = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/activate",
        json={},
        headers=_auth(admin_id, ["admin"]),
    )
    assert activate.status_code == 404


async def test_credentials_endpoints_survive(
    client: AsyncClient, clean_state: None
) -> None:
    """User-owned credential endpoints are unaffected by the retirement."""
    del clean_state
    user_id = await _new_user()

    listed = await client.get("/v1/credentials", headers=_auth(user_id))
    assert listed.status_code == 200
    assert "credentials" in listed.json()


async def test_register_rejects_self_selected_attestor(
    client: AsyncClient, clean_state: None
) -> None:
    """Registration no longer accepts the attestor role (422, org-derived only)."""
    del clean_state
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": f"reg-{uuid4().hex[:8]}@auracles.space",
            "password": "CorrectHorse9",
            "display_name": "Would-be Attestor",
            "roles": ["attestor"],
        },
    )
    assert response.status_code == 422


# Note: the derived-role grant path (org approval → members gain the attestor
# role) is exercised end-to-end by
# tests/integration/test_org_attestor_admin_endpoints.py::
# test_full_gate_walk_to_approval and the org attestor lifecycle test, both of
# which remain green after this retirement.
