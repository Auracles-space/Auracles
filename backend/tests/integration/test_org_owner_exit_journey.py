"""The owner's whole exit: wind down, close the organization, delete the account.

Each link in this chain was already tested on its own and each one worked.
The chain did not: closing refuses while a capability is active, every
capability status change was admin-only, and account deletion refuses while
you are sole owner of an org with an active capability. An owner was sealed
in, and QA found it from the inside — "it keeps asking me to wind down first
but there is nothing to wind down".

So this suite walks the journey rather than the parts. A test per link would
not have caught the original bug, and would not catch its return.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.modules.organizations.models import OrgCapability, OrgMember
from tests.conftest import grant_step_up, verify_org_kyb
from tests.integration.test_auth_sessions import FakeRedis
from tests.integration.test_org_admin_endpoints import add_member
from tests.integration.test_organizations_endpoints import (  # noqa: F401
    auth,
    clean_orgs,
    create_org,
    create_user,
    migrated_database,
)

# Re-exported so the imported fixtures are not read as unused and then
# redefined by the test parameters that request them — the pattern the other
# organization suites follow.
__all__ = ["clean_orgs", "migrated_database"]

pytestmark = pytest.mark.usefixtures("migrated_database")


async def _capability_status(org_id: str, capability: str) -> str | None:
    """Return one capability's status, or None when the row is absent."""
    async with async_session_factory() as session:
        return await session.scalar(
            select(OrgCapability.status).where(
                OrgCapability.org_id == UUID(org_id),
                OrgCapability.capability == capability,
            )
        )


async def test_owner_winds_down_closes_and_then_deletes_their_account(
    client: AsyncClient,
    clean_orgs: FakeRedis,
) -> None:
    """The full exit succeeds, in the order the product asks for it.

    Before the wind-down endpoints existed this stopped at the first step
    with a 409 naming an action the owner had no control for.
    """
    owner_id = await create_user("exit-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "exit-org")
    await verify_org_kyb(org["id"])
    for capability in ("contributor", "operator"):
        activated = await client.post(
            f"/v1/orgs/{org['id']}/{capability}-capability/activate",
            headers=auth(token),
        )
        assert activated.status_code == 200, activated.text
    await grant_step_up(clean_orgs, owner_id)

    # 1. The close is refused while a capability is still active. This is the
    #    409 QA was stuck behind.
    blocked = await client.delete(f"/v1/orgs/{org['id']}", headers=auth(token))
    assert blocked.status_code == 409, blocked.text
    assert "capabilit" in blocked.json()["detail"].lower()

    # 2. The owner stands each one down themselves.
    for capability in ("contributor", "operator"):
        stood_down = await client.post(
            f"/v1/orgs/{org['id']}/{capability}-capability/withdraw",
            headers=auth(token),
        )
        assert stood_down.status_code == 204, stood_down.text
        assert await _capability_status(org["id"], capability) == "withdrawn"

    # 3. The close now succeeds.
    closed = await client.delete(f"/v1/orgs/{org['id']}", headers=auth(token))
    assert closed.status_code == 204, closed.text

    # 4. And account deletion is no longer blocked by the organization.
    deletion = await client.post(
        "/v1/gdpr/account-deletion",
        headers=auth(token),
        json={"password": "CorrectHorse9"},
    )
    assert deletion.status_code == 202, deletion.text
    assert deletion.json()["blocked_reasons"] == []


async def test_account_deletion_names_the_org_until_it_is_wound_down(
    client: AsyncClient,
    clean_orgs: FakeRedis,
) -> None:
    """Deletion stays blocked while the org trades, and says which org.

    The blocker is correct and must survive: an owner cannot walk away from an
    organization that is still selling. What changed is that they can now act
    on it without an administrator.
    """
    owner_id = await create_user("exit-blocked-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "exit-blocked-org")
    await verify_org_kyb(org["id"])
    await client.post(
        f"/v1/orgs/{org['id']}/contributor-capability/activate",
        headers=auth(token),
    )

    blocked = await client.post(
        "/v1/gdpr/account-deletion",
        headers=auth(token),
        json={"password": "CorrectHorse9"},
    )

    assert blocked.status_code == 409, blocked.text
    reasons = blocked.json()["blocked_reasons"]
    assert [reason["code"] for reason in reasons] == ["sole_owner"]
    assert "exit-blocked-org" in reasons[0]["message"]


async def test_transferring_ownership_is_the_other_way_out(
    client: AsyncClient,
    clean_orgs: FakeRedis,
) -> None:
    """Handing the organization to someone else also unblocks deletion.

    `uq_org_members_single_owner` means an org has exactly one owner, so the
    `sole_owner` blocker fires for every owner of a trading org. Winding down
    is therefore not the only exit: an owner who wants the organization to
    carry on transfers it instead, and the blocker follows the ownership.
    """
    owner_id = await create_user("exit-handover-owner")
    heir_id = await create_user("exit-handover-heir")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "exit-handover-org")
    await add_member(str(org["id"]), heir_id, "admin")
    await verify_org_kyb(org["id"])
    await client.post(
        f"/v1/orgs/{org['id']}/contributor-capability/activate",
        headers=auth(token),
    )
    await grant_step_up(clean_orgs, owner_id)

    blocked = await client.post(
        "/v1/gdpr/account-deletion",
        headers=auth(token),
        json={"password": "CorrectHorse9"},
    )
    assert blocked.status_code == 409, blocked.text

    async with async_session_factory() as session:
        heir_member_id = await session.scalar(
            select(OrgMember.id).where(
                OrgMember.org_id == UUID(org["id"]),
                OrgMember.user_id == heir_id,
            )
        )
    handed_over = await client.post(
        f"/v1/orgs/{org['id']}/transfer-ownership",
        headers=auth(token),
        json={"new_owner_member_id": str(heir_member_id)},
    )
    assert handed_over.status_code in (200, 204), handed_over.text

    deletion = await client.post(
        "/v1/gdpr/account-deletion",
        headers=auth(token),
        json={"password": "CorrectHorse9"},
    )

    assert deletion.status_code == 202, deletion.text
    # The organization keeps trading under its new owner.
    assert await _capability_status(org["id"], "contributor") == "active"
