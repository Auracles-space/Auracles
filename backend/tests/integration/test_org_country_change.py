"""Integration tests for changing an organization's country.

The country picks the payout rail (Paystack for NG, Stripe elsewhere) and gives
the registration number its meaning, so owners may correct it only until
business verification is pending or verified or a payout account exists.
Covers ``PATCH /v1/orgs/{org_id}/country`` (owner role, step-up window, locks,
audit, owner notices).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.modules.financials.models import PayoutAccount
from app.modules.organizations.models import OrgLegalProfile
from app.shared.models.audit_log import AuditLog
from tests.conftest import open_step_up_window, verify_org_kyb
from tests.integration.test_auth_sessions import FakeRedis
from tests.integration.test_org_admin_endpoints import record_owner_notifications
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


async def _owner_org(
    client: AsyncClient, redis: FakeRedis, prefix: str
) -> tuple[UUID, str, dict[str, object]]:
    """Create an unverified GB org whose 2FA owner holds a step-up window."""
    owner_id = await create_user(f"{prefix}-owner", totp_enabled=True)
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, prefix, verified=False)
    await open_step_up_window(redis, owner_id)
    return owner_id, token, org


async def _change(
    client: AsyncClient, org: dict[str, object], token: str, country: str
):
    """PATCH the org country."""
    return await client.patch(
        f"/v1/orgs/{org['id']}/country", json={"country": country}, headers=auth(token)
    )


async def _set_kyb_status(org_id: object, kyb_status: str) -> None:
    """Seed the org legal profile with ``kyb_status``."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgLegalProfile(
                    org_id=UUID(str(org_id)),
                    legal_name="Ikeji Advisory Ltd",
                    kyb_status=kyb_status,
                )
            )


async def test_owner_changes_country_audits_and_notifies_other_owners(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unverified org's owner can move it to NG; the change is audited."""
    del migrated_database
    recorder = record_owner_notifications(monkeypatch)
    owner_id, token, org = await _owner_org(client, clean_orgs, "ctry")

    response = await _change(client, org, token, "ng")

    assert response.status_code == 200, response.text
    assert response.json()["country"] == "NG"
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "org_country_changed",
                AuditLog.target_id == UUID(str(org["id"])),
            )
        )
    assert audit is not None
    assert audit.actor_id == owner_id
    assert audit.metadata_ == {"from": "GB", "to": "NG"}
    # Only one owner exists, and the actor never hears about their own change.
    assert [
        c for c in recorder.sent if c["notification_type"] == "org_profile_updated"
    ] == []


async def test_rejected_verification_still_allows_the_change(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """A wrong country is a likely rejection reason, so rejection unlocks it."""
    del migrated_database
    _owner_id, token, org = await _owner_org(client, clean_orgs, "rej")
    await _set_kyb_status(org["id"], "rejected")

    response = await _change(client, org, token, "NG")

    assert response.status_code == 200, response.text


@pytest.mark.parametrize("kyb_status", ["pending", "verified"])
async def test_pending_or_verified_business_verification_locks_country(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: FakeRedis,
    kyb_status: str,
) -> None:
    """Verification under review or passed is tied to the country, so 409."""
    del migrated_database
    _owner_id, token, org = await _owner_org(client, clean_orgs, f"lk{kyb_status[:3]}")
    if kyb_status == "verified":
        await verify_org_kyb(org["id"])
    else:
        await _set_kyb_status(org["id"], kyb_status)

    response = await _change(client, org, token, "NG")

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "org_country_locked"


async def test_payout_account_locks_country(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """A payout account settles on the country's rail, so it locks the country."""
    del migrated_database
    _owner_id, token, org = await _owner_org(client, clean_orgs, "pay")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                PayoutAccount(
                    org_id=UUID(str(org["id"])),
                    provider="stripe",
                    provider_account_id=f"acct_{uuid4().hex[:12]}",
                    provider_account_lookup_hash=uuid4().hex + uuid4().hex,
                    account_type="express",
                )
            )

    response = await _change(client, org, token, "NG")

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "org_country_locked"


async def test_owner_without_step_up_window_is_refused(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """The change needs an open step-up window."""
    del migrated_database
    owner_id = await create_user("nsu-owner", totp_enabled=True)
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "nsu", verified=False)

    response = await _change(client, org, token, "NG")

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "step_up_required"


async def test_org_admin_who_is_not_owner_is_refused(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """Only owners may change the country, even with a step-up window."""
    del migrated_database
    _owner_id, _token, org = await _owner_org(client, clean_orgs, "cadm")
    admin_id = await create_user("cadm-admin", totp_enabled=True)
    await add_member(str(org["id"]), admin_id, "admin")
    await open_step_up_window(clean_orgs, admin_id)

    response = await _change(client, org, create_access_token(admin_id, []), "NG")

    assert response.status_code == 403


@pytest.mark.parametrize("country", ["GB", "N", "NGA", "1G"])
async def test_same_or_malformed_country_is_422(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: FakeRedis,
    country: str,
) -> None:
    """The current country or a non-alpha-2 code is refused."""
    del migrated_database
    _owner_id, token, org = await _owner_org(client, clean_orgs, "bad")

    response = await _change(client, org, token, country)

    assert response.status_code == 422
