"""Integration tests for the Organizations Slice A security hardening.

Covers the spec's "correctness and money safety" slice: step-up on org
purchase, owner-only payout authority (Decision 3), one payout in flight per
organization, step-up on business-verification writes, a rate limit on the
public profile, website scheme validation, and the ``{error_code, message}``
error-detail contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.modules.auth.models import User
from app.modules.financials import service as financials_service
from app.modules.financials.models import Payout
from app.modules.financials.schemas import PayoutRequest, PurchaseRequest
from app.modules.organizations.models import Organization, OrgCapability
from app.modules.organizations.router import ORG_PUBLIC_PROFILE_LIMIT
from app.modules.organizations.schemas import (
    OrganizationCreateRequest,
    OrganizationUpdateRequest,
)
from tests.conftest import open_step_up_window
from tests.integration.test_auth_sessions import FakeRedis
from tests.integration.test_org_financials_endpoints import (
    _add_member as _fin_add_member,
)
from tests.integration.test_org_financials_endpoints import (
    _attestor_org,
    _FakePayoutTask,
    _org_attestation_report_submitted,
    _org_payout_account,
    _release,
    clean_state,
    db_session,
)
from tests.integration.test_organizations_endpoints import (
    add_member,
    auth,
    clean_orgs,
    create_org,
    create_user,
    migrated_database,
)

pytestmark = pytest.mark.asyncio

# `clean_orgs` resets org rows for the endpoint tests; the two service-level
# tests seed attestation and payout rows, which only the financials suite's
# `clean_state` (via `db_session`) knows how to unwind in FK-safe order.
__all__ = ["clean_orgs", "clean_state", "db_session", "migrated_database"]


async def _activate_capability(org_id: str, capability: str) -> None:
    """Seed one active organization capability directly."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=UUID(org_id), capability=capability, status="active"
                )
            )


# --- Task 1: step-up on org purchase ---------------------------------------


async def test_org_purchase_requires_step_up_window(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """Org checkout refuses `step_up_required` without a window and proceeds with one.

    Decision 3 keeps purchase open to org admins but adds step-up. With the
    window open the request reaches the service, which answers 404 for an
    unknown Framework — proof the gate itself passed.
    """
    del migrated_database
    owner_id = await create_user("buy-owner", totp_enabled=True)
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "buy")
    await _activate_capability(str(org["id"]), "operator")
    path = f"/v1/orgs/{org['id']}/frameworks/{uuid4()}/purchase"

    no_window = await client.post(
        path, json={"license_type": "single_user"}, headers=auth(token)
    )
    await open_step_up_window(clean_orgs, owner_id)
    with_window = await client.post(
        path, json={"license_type": "single_user"}, headers=auth(token)
    )

    assert no_window.status_code == 403
    assert no_window.json()["detail"]["error_code"] == "step_up_required"
    assert with_window.status_code == 404


# --- Task 2: owner-only payout authority ------------------------------------


async def test_payout_account_onboarding_is_owner_only_with_step_up(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the owner, inside a step-up window, can add a payout destination."""
    del migrated_database

    async def _fake_express(*, email: str, country: str) -> SimpleNamespace:
        return SimpleNamespace(id=f"acct_{uuid4().hex}")

    async def _fake_link(
        *, account_id: str, refresh_url: str, return_url: str
    ) -> SimpleNamespace:
        return SimpleNamespace(url="https://connect.stripe.test/onboard")

    monkeypatch.setattr(
        financials_service.stripe, "create_express_account", _fake_express
    )
    monkeypatch.setattr(financials_service.stripe, "create_account_link", _fake_link)
    owner_id = await create_user("po-owner", totp_enabled=True)
    admin_id = await create_user("po-admin", totp_enabled=True)
    owner_token = create_access_token(owner_id, [])
    admin_token = create_access_token(admin_id, [])
    org = await create_org(client, owner_token, "po")
    await add_member(str(org["id"]), admin_id, "admin")
    await open_step_up_window(clean_orgs, admin_id)
    path = f"/v1/orgs/{org['id']}/financials/payout-accounts"
    body = {
        "provider": "stripe",
        "refresh_url": "https://app.test/refresh",
        "return_url": "https://app.test/return",
    }

    as_admin = await client.post(path, json=body, headers=auth(admin_token))
    owner_no_window = await client.post(path, json=body, headers=auth(owner_token))
    await open_step_up_window(clean_orgs, owner_id)
    as_owner = await client.post(path, json=body, headers=auth(owner_token))

    assert as_admin.status_code == 403
    assert as_admin.json()["detail"]["error_code"] == "org_role_required"
    assert owner_no_window.status_code == 403
    assert owner_no_window.json()["detail"]["error_code"] == "step_up_required"
    assert as_owner.status_code == 200


async def test_payout_request_is_owner_only_with_step_up(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """Payout requests are refused for org admins and pass the gate for owners.

    An owner with an open window reaches the service, which rejects the
    non-platform currency with 422 — proof the role and step-up gates passed.
    """
    del migrated_database
    owner_id = await create_user("py-owner", totp_enabled=True)
    admin_id = await create_user("py-admin", totp_enabled=True)
    owner_token = create_access_token(owner_id, [])
    admin_token = create_access_token(admin_id, [])
    org = await create_org(client, owner_token, "py")
    await add_member(str(org["id"]), admin_id, "admin")
    await open_step_up_window(clean_orgs, admin_id)
    await open_step_up_window(clean_orgs, owner_id)
    path = f"/v1/orgs/{org['id']}/financials/payouts"
    body = {
        "amount": "100.00",
        "currency": "EUR",
        "payout_account_id": str(uuid4()),
    }

    as_admin = await client.post(path, json=body, headers=auth(admin_token))
    as_owner = await client.post(path, json=body, headers=auth(owner_token))

    assert as_admin.status_code == 403
    assert as_admin.json()["detail"]["error_code"] == "org_role_required"
    assert as_owner.status_code == 422


# --- Task 3: one payout in flight per organization ---------------------------


async def test_second_org_payout_while_one_is_pending_conflicts(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second payout request while one is pending or processing returns 409."""
    fake_task = _FakePayoutTask()
    monkeypatch.setattr(financials_service, "process_payout", fake_task, raising=False)
    org_id, owner_id, _secret = await _attestor_org()
    member_id, _ = await _fin_add_member(org_id)
    requestor_id, attestation_id = await _org_attestation_report_submitted(
        org_id, member_id
    )
    await _release(requestor_id, attestation_id)
    account_id = await _org_payout_account(org_id)
    owner = await db_session.get(User, owner_id)
    payload = PayoutRequest(
        amount=Decimal("100.00"), currency="USD", payout_account_id=account_id
    )

    first = await financials_service.request_org_payout(
        db_session, org_id=org_id, actor=owner, payload=payload
    )
    # The first request's commit expired the loaded actor; the route loads a
    # fresh user per request, so mirror that here.
    await db_session.refresh(owner)
    with pytest.raises(HTTPException) as excinfo:
        await financials_service.request_org_payout(
            db_session, org_id=org_id, actor=owner, payload=payload
        )

    assert first.net_amount == Decimal("100.00")
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == (
        "A payout is already in progress for this organization."
    )
    async with async_session_factory() as session:
        payouts = (
            await session.scalars(select(Payout).where(Payout.org_id == org_id))
        ).all()
    assert len(payouts) == 1


# --- Task 4: step-up on business-verification writes -------------------------


async def test_kyb_document_and_submit_writes_require_step_up(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """Incorporation document add/remove and KYB submit refuse without a window."""
    del migrated_database
    owner_id = await create_user("kyb-owner", totp_enabled=True)
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "kyb", verified=False)
    base = f"/v1/orgs/{org['id']}/kyb"

    added = await client.post(
        f"{base}/incorporation-document",
        json={
            "file_name": "certificate.pdf",
            "content_type": "application/pdf",
            "size_bytes": 4096,
        },
        headers=auth(token),
    )
    removed = await client.request(
        "DELETE",
        f"{base}/incorporation-document",
        json={"s3_key": "org-incorporation-docs/seed/cert.pdf"},
        headers=auth(token),
    )
    submitted = await client.post(f"{base}/submit", headers=auth(token))

    for response in (added, removed, submitted):
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["error_code"] == "step_up_required"


# --- Task 5: public profile rate limit -----------------------------------------


async def test_public_org_profile_is_rate_limited(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """A burst of public profile reads past the window returns 429."""
    del migrated_database
    user_id = await create_user("org-public-rl")
    token = create_access_token(user_id, [])
    org = await create_org(client, token, "pubrl")

    statuses = [
        (await client.get(f"/v1/orgs/{org['slug']}")).status_code
        for _ in range(ORG_PUBLIC_PROFILE_LIMIT + 1)
    ]

    assert statuses[:ORG_PUBLIC_PROFILE_LIMIT] == [200] * ORG_PUBLIC_PROFILE_LIMIT
    assert statuses[-1] == 429


# --- Task 6: website scheme validation -----------------------------------------


@pytest.mark.parametrize(
    "website",
    ["javascript:alert(1)", "ftp://files.example.com", "example.com"],
)
async def test_org_website_must_be_absolute_http_url(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis, website: str
) -> None:
    """Create and update refuse a website that is not an absolute http(s) URL."""
    del migrated_database
    user_id = await create_user("org-web")
    token = create_access_token(user_id, [])
    org = await create_org(client, token, "web")

    created = await client.post(
        "/v1/orgs",
        json={
            "slug": f"web-{uuid4().hex[:6]}",
            "name": "Web Org",
            "country": "GB",
            "website": website,
        },
        headers=auth(token),
    )
    updated = await client.patch(
        f"/v1/orgs/{org['id']}", json={"website": website}, headers=auth(token)
    )

    assert created.status_code == 422
    assert updated.status_code == 422


async def test_org_website_is_trimmed_and_blank_becomes_null(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """Whitespace around a valid website is stripped and a blank one reads as null."""
    del migrated_database
    assert (
        OrganizationCreateRequest(
            slug="blank", name="Blank", country="GB", website="   "
        ).website
        is None
    )
    assert OrganizationUpdateRequest(website="").website is None
    user_id = await create_user("org-web-ok")
    token = create_access_token(user_id, [])

    created = await client.post(
        "/v1/orgs",
        json={
            "slug": f"webok-{uuid4().hex[:6]}",
            "name": "Web Org",
            "country": "GB",
            "website": "  https://example.com/team  ",
        },
        headers=auth(token),
    )

    assert created.status_code == 201, created.text
    assert created.json()["website"] == "https://example.com/team"


# --- Task 7: {error_code, message} error details -------------------------------


async def test_org_suspended_denial_carries_a_message(
    client: AsyncClient, migrated_database: None, clean_orgs: FakeRedis
) -> None:
    """Dependency-layer denials answer both an error code and a human message."""
    del migrated_database
    owner_id = await create_user("org-msg")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "msg")
    async with async_session_factory() as session:
        async with session.begin():
            organization = await session.get(Organization, UUID(str(org["id"])))
            assert organization is not None
            organization.suspended_at = datetime.now(UTC)

    response = await client.patch(
        f"/v1/orgs/{org['id']}", json={"name": "Blocked"}, headers=auth(token)
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["error_code"] == "org_suspended"
    assert isinstance(detail["message"], str) and detail["message"]


async def test_capability_suspended_purchase_denial_carries_a_message(
    db_session,
) -> None:
    """The financials capability gate answers both an error code and a message."""
    owner_id = await create_user("cap-msg")
    async with async_session_factory() as session:
        async with session.begin():
            organization = Organization(
                slug=f"capmsg-{uuid4().hex[:6]}",
                name="Cap Msg Org",
                country="GB",
                created_by=owner_id,
            )
            session.add(organization)
            await session.flush()
            org_id = organization.id
    owner = await db_session.get(User, owner_id)

    with pytest.raises(HTTPException) as excinfo:
        await financials_service.create_org_framework_purchase(
            db_session,
            org_id=org_id,
            actor=owner,
            framework_id=uuid4(),
            payload=PurchaseRequest(license_type="single_user"),
        )

    assert excinfo.value.status_code == 403
    detail = excinfo.value.detail
    assert detail["error_code"] == "capability_suspended"
    assert isinstance(detail["message"], str) and detail["message"]
