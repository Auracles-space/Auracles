"""Integration tests for the organization slug HTTP wiring (Decision 5).

Covers ``PATCH /v1/orgs/{org_id}/slug`` (owner role, step-up window, rate
limit), public profile resolution of past slugs with ``canonical_slug``, and
organization creation refusing a slug reserved in ``org_slug_history``.
Spec: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md
§Slug change.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.modules.organizations.models import Organization
from app.modules.organizations.router import ORG_SLUG_CHANGE_LIMIT
from tests.conftest import open_step_up_window
from tests.integration.test_auth_sessions import FakeRedis
from tests.integration.test_organizations_endpoints import (
    add_member,
    auth,
    clean_orgs,
    create_org,
    create_user,
    migrated_database,
)

pytestmark = pytest.mark.asyncio

__all__ = ["clean_orgs", "migrated_database"]


def _slug(prefix: str) -> str:
    """Return a unique valid slug."""
    return f"{prefix}-{uuid4().hex[:6]}"


async def _enrolled_owner_org(
    client: AsyncClient, prefix: str
) -> tuple[UUID, str, dict[str, object]]:
    """Create a 2FA-enrolled owner and their org; return (owner_id, token, org)."""
    owner_id = await create_user(f"{prefix}-owner", totp_enabled=True)
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, prefix)
    return owner_id, token, org


async def test_owner_without_step_up_window_is_refused(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """An owner must hold an open step-up window to change the slug."""
    del migrated_database
    _owner_id, token, org = await _enrolled_owner_org(client, "su")

    response = await client.patch(
        f"/v1/orgs/{org['id']}/slug", json={"slug": _slug("new")}, headers=auth(token)
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "step_up_required"


async def test_org_admin_who_is_not_owner_is_refused(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """An org admin is refused even inside a step-up window."""
    del migrated_database
    _owner_id, _token, org = await _enrolled_owner_org(client, "adm")
    admin_id = await create_user("adm-admin", totp_enabled=True)
    await add_member(str(org["id"]), admin_id, "admin")
    await open_step_up_window(clean_orgs, admin_id)

    response = await client.patch(
        f"/v1/orgs/{org['id']}/slug",
        json={"slug": _slug("new")},
        headers=auth(create_access_token(admin_id, [])),
    )

    assert response.status_code == 403


async def test_owner_with_window_changes_slug(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """An owner inside a window gets 200 and the organization with its new slug."""
    del migrated_database
    owner_id, token, org = await _enrolled_owner_org(client, "ok")
    await open_step_up_window(clean_orgs, owner_id)
    new_slug = _slug("Renamed").lower()

    response = await client.patch(
        f"/v1/orgs/{org['id']}/slug",
        json={"slug": new_slug.upper()},
        headers=auth(token),
    )

    assert response.status_code == 200, response.text
    assert response.json()["id"] == org["id"]
    assert response.json()["slug"] == new_slug


async def test_taken_slug_is_409(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """A slug held by another organization answers 409."""
    del migrated_database
    owner_id, token, org = await _enrolled_owner_org(client, "tk")
    _other_owner, _other_token, other = await _enrolled_owner_org(client, "tk-other")
    await open_step_up_window(clean_orgs, owner_id)

    response = await client.patch(
        f"/v1/orgs/{org['id']}/slug",
        json={"slug": other["slug"]},
        headers=auth(token),
    )

    assert response.status_code == 409


async def test_slug_change_is_rate_limited(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """Slug changes are capped per organization, like organization creation."""
    del migrated_database
    owner_id, token, org = await _enrolled_owner_org(client, "rl")
    await open_step_up_window(clean_orgs, owner_id)

    statuses = []
    for _ in range(ORG_SLUG_CHANGE_LIMIT + 1):
        response = await client.patch(
            f"/v1/orgs/{org['id']}/slug",
            json={"slug": _slug("rl")},
            headers=auth(token),
        )
        statuses.append(response.status_code)

    assert statuses[:ORG_SLUG_CHANGE_LIMIT] == [200] * ORG_SLUG_CHANGE_LIMIT
    assert statuses[-1] == 429


async def test_public_profile_resolves_past_slug_with_canonical_slug(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """A past slug returns the profile and names the current slug as canonical."""
    del migrated_database
    owner_id, token, org = await _enrolled_owner_org(client, "pub")
    old_slug = str(org["slug"])
    await open_step_up_window(clean_orgs, owner_id)
    new_slug = _slug("pub-new")
    changed = await client.patch(
        f"/v1/orgs/{org['id']}/slug", json={"slug": new_slug}, headers=auth(token)
    )
    assert changed.status_code == 200

    past = await client.get(f"/v1/orgs/{old_slug}")
    current = await client.get(f"/v1/orgs/{new_slug}")

    assert past.status_code == 200
    assert past.json()["slug"] == new_slug
    assert past.json()["canonical_slug"] == new_slug
    assert current.status_code == 200
    assert current.json()["canonical_slug"] == new_slug


async def test_public_profile_unknown_and_suspended_are_404(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """Unknown slugs and suspended organizations stay hidden."""
    del migrated_database
    _owner_id, _token, org = await _enrolled_owner_org(client, "susp")
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Organization)
                .where(Organization.id == UUID(str(org["id"])))
                .values(suspended_at=datetime.now(UTC))
            )

    unknown = await client.get(f"/v1/orgs/{_slug('nobody')}")
    suspended = await client.get(f"/v1/orgs/{org['slug']}")

    assert unknown.status_code == 404
    assert suspended.status_code == 404


async def test_create_org_refuses_slug_in_history(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """A slug reserved in another organization's history cannot be created."""
    del migrated_database
    owner_id, token, org = await _enrolled_owner_org(client, "hist")
    old_slug = str(org["slug"])
    await open_step_up_window(clean_orgs, owner_id)
    changed = await client.patch(
        f"/v1/orgs/{org['id']}/slug",
        json={"slug": _slug("hist-new")},
        headers=auth(token),
    )
    assert changed.status_code == 200
    squatter = create_access_token(await create_user("squatter"), [])

    response = await client.post(
        "/v1/orgs",
        json={"slug": old_slug, "name": "Impostor", "country": "GB"},
        headers=auth(squatter),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Organization slug already exists."
