"""Integration tests for the admin organization detail read endpoints.

Covers the Decision 1 admin org detail page (Slice D): overview, members,
verification documents (presigned + audited), financials, frameworks and
licenses, in-flight attestations, and the org audit trail.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory
from app.core.security import (
    create_access_token,
    encrypt_payout_provider_account_id,
    hash_payout_provider_account_id,
)
from app.integrations import s3
from app.modules.attestation.models import Attestation
from app.modules.financials.models import Payout, PayoutAccount, Transaction
from app.modules.frameworks.models import Framework, License, LicenseGrant
from app.modules.organizations.models import (
    OrgInvitation,
    OrgLegalProfile,
    OrgTeam,
    OrgTeamMember,
)
from app.shared.models.audit_log import AuditLog
from tests.integration.test_org_admin_endpoints import create_platform_admin
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

SUB_ROUTES = [
    "members",
    "verification",
    "financials",
    "frameworks",
    "attestations",
    "audit",
]


@dataclass
class SeededOrg:
    """Ids of everything seeded for one admin org detail scenario."""

    org_id: str
    owner_id: UUID
    member_user_id: UUID
    member_id: UUID
    admin_headers: dict[str, str]
    signed_keys: list[str] = field(default_factory=list)


@dataclass
class _Tracked:
    """Rows the fixture must delete before org cleanup runs."""

    org_ids: list[UUID] = field(default_factory=list)
    user_ids: list[UUID] = field(default_factory=list)


@pytest.fixture
async def detail_env(
    client: AsyncClient,
    clean_orgs: object,
    migrated_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncClient, list[str], _Tracked]]:
    """Stub S3 signing and delete non-org rows seeded by each test.

    Frameworks, licenses, payouts, and attestations reference organizations
    without cascading, so they are removed here before ``clean_orgs`` tears
    the organizations down.
    """
    del clean_orgs, migrated_database
    signed_keys: list[str] = []

    def fake_presigned_get(
        bucket: str,
        key: str,
        expires_in: int,
        *,
        download_name: str | None = None,
    ) -> str:
        """Return a deterministic signed URL and record the key and TTL."""
        del bucket, download_name
        signed_keys.append(key)
        assert expires_in == 300
        return f"https://downloads.example.test/signed?id={len(signed_keys)}"

    def fake_object_exists(bucket: str, key: str) -> bool:
        """Report every document as uploaded."""
        del bucket, key
        return True

    monkeypatch.setattr(s3.storage, "presigned_get", fake_presigned_get)
    monkeypatch.setattr(s3.storage, "object_exists", fake_object_exists)
    tracked = _Tracked()
    try:
        yield client, signed_keys, tracked
    finally:
        async with async_session_factory() as session:
            async with session.begin():
                for org_id in tracked.org_ids:
                    await session.execute(
                        delete(Attestation).where(Attestation.attestor_org_id == org_id)
                    )
                    license_ids = select(License.id).where(
                        License.licensee_org_id == org_id
                    )
                    await session.execute(
                        delete(LicenseGrant).where(
                            LicenseGrant.license_id.in_(license_ids)
                        )
                    )
                    await session.execute(
                        delete(License).where(License.licensee_org_id == org_id)
                    )
                    await session.execute(delete(Payout).where(Payout.org_id == org_id))
                    await session.execute(
                        delete(PayoutAccount).where(PayoutAccount.org_id == org_id)
                    )
                    await session.execute(
                        delete(Transaction).where(Transaction.payer_org_id == org_id)
                    )
                    await session.execute(
                        delete(Framework).where(Framework.contributor_org_id == org_id)
                    )
                    await session.execute(
                        delete(OrgInvitation).where(OrgInvitation.org_id == org_id)
                    )
                for user_id in tracked.user_ids:
                    await session.execute(
                        delete(Framework).where(Framework.contributor_id == user_id)
                    )


async def _seed_org(
    client: AsyncClient, signed_keys: list[str], tracked: _Tracked
) -> SeededOrg:
    """Seed an org with an owner, a teamed member, and one row per panel."""
    _admin_id, admin_headers = await create_platform_admin()
    owner_id = await create_user("detail-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "detailorg")
    org_id = UUID(str(org["id"]))
    tracked.org_ids.append(org_id)
    member_user_id = await create_user("detail-member")
    member_id = await add_member(str(org_id), member_user_id, "member")
    seller_id = await create_user("detail-seller")
    tracked.user_ids.append(seller_id)
    now = datetime.now(UTC)

    async with async_session_factory() as session:
        async with session.begin():
            profile = await session.scalar(
                select(OrgLegalProfile).where(OrgLegalProfile.org_id == org_id)
            )
            assert profile is not None
            profile.incorporation_doc_keys = [
                f"org-incorporation-docs/{org_id}/{uuid4()}-certificate.pdf"
            ]
            profile.tax_document_type = "other"
            profile.tax_document_key = f"org-tax-docs/{org_id}/{uuid4()}-tax.pdf"
            team = OrgTeam(org_id=org_id, name="Reviewers")
            session.add(team)
            await session.flush()
            session.add(OrgTeamMember(team_id=team.id, member_id=member_id))
            session.add(
                OrgInvitation(
                    org_id=org_id,
                    email=f"invitee-{uuid4().hex[:6]}@auracles.space",
                    role="member",
                    invited_by=owner_id,
                    status="pending",
                    token_hash=uuid4().hex,
                    expires_at=now + timedelta(days=7),
                )
            )
            owned = Framework(
                contributor_org_id=org_id,
                title="Org Owned Framework",
                description="Owned by the org.",
                category="compliance",
                price=Decimal("50.00"),
                license_types=["team"],
            )
            licensed = Framework(
                contributor_id=seller_id,
                title="Licensed Framework",
                description="Bought by the org.",
                category="compliance",
                price=Decimal("199.00"),
                license_types=["team"],
            )
            session.add_all([owned, licensed])
            await session.flush()
            license_row = License(
                framework_id=licensed.id,
                licensee_org_id=org_id,
                license_type="team",
                status="active",
                version_at_grant="1.0.0",
            )
            session.add(license_row)
            await session.flush()
            session.add(LicenseGrant(license_id=license_row.id, team_id=team.id))
            session.add(
                Attestation(
                    target_type="framework",
                    target_id=licensed.id,
                    requestor_id=seller_id,
                    attestor_org_id=org_id,
                    reviewing_member_id=member_id,
                    status="in_review",
                    review_type="quality",
                    fee_amount=Decimal("500.00"),
                    currency="USD",
                    requested_specializations=["tax"],
                    requested_jurisdictions=["US"],
                    completion_due_at=now + timedelta(days=5),
                )
            )
            account = PayoutAccount(
                org_id=org_id,
                provider="paystack",
                provider_account_id=encrypt_payout_provider_account_id("0123456789"),
                provider_account_lookup_hash=hash_payout_provider_account_id(
                    f"0123456789-{uuid4().hex}"
                ),
                account_type="nuban",
                is_default=True,
                verified_at=now,
            )
            session.add(account)
            await session.flush()
            session.add(
                Payout(
                    org_id=org_id,
                    payout_account_id=account.id,
                    amount=Decimal("100.00"),
                    currency="USD",
                    commission_deducted=Decimal("0.00"),
                    net_amount=Decimal("100.00"),
                    status="completed",
                    completed_at=now,
                )
            )
            session.add_all(
                [
                    Transaction(
                        payer_org_id=org_id,
                        payee_id=seller_id,
                        amount=Decimal("199.00"),
                        currency="USD",
                        platform_commission=Decimal("0.00"),
                        net_amount=Decimal("199.00"),
                        transaction_type="purchase",
                        status="completed",
                        provider="stripe",
                        provider_ref=f"pi_detail_{uuid4().hex[:8]}",
                    ),
                    Transaction(
                        payer_org_id=org_id,
                        payee_id=seller_id,
                        amount=Decimal("199.00"),
                        currency="USD",
                        platform_commission=Decimal("0.00"),
                        net_amount=Decimal("199.00"),
                        transaction_type="purchase",
                        status="failed",
                        provider="stripe",
                        provider_ref=f"pi_detail_{uuid4().hex[:8]}",
                    ),
                ]
            )

    suspended = await client.post(
        f"/v1/admin/orgs/{org_id}/suspend",
        json={"reason": "Policy breach recorded by the trust team."},
        headers=admin_headers,
    )
    assert suspended.status_code == 204, suspended.text
    reinstated = await client.post(
        f"/v1/admin/orgs/{org_id}/reinstate", headers=admin_headers
    )
    assert reinstated.status_code == 204, reinstated.text
    return SeededOrg(
        org_id=str(org_id),
        owner_id=owner_id,
        member_user_id=member_user_id,
        member_id=member_id,
        admin_headers=admin_headers,
        signed_keys=signed_keys,
    )


async def test_detail_requires_authentication(
    detail_env: tuple[AsyncClient, list[str], _Tracked],
) -> None:
    """An unauthenticated request for the org overview is refused with 401."""
    client, _, _ = detail_env
    response = await client.get(f"/v1/admin/orgs/{uuid4()}/detail")
    assert response.status_code == 401


async def test_every_detail_route_refuses_non_admins(
    detail_env: tuple[AsyncClient, list[str], _Tracked],
) -> None:
    """A signed-in user without the admin role gets 403 on every panel."""
    client, _, _ = detail_env
    user_id = await create_user("detail-nonadmin")
    headers = auth(create_access_token(user_id, ["operator"]))
    org_id = uuid4()
    for route in ["detail", *SUB_ROUTES]:
        response = await client.get(f"/v1/admin/orgs/{org_id}/{route}", headers=headers)
        assert response.status_code == 403, route


async def test_every_detail_route_404s_for_unknown_org(
    detail_env: tuple[AsyncClient, list[str], _Tracked],
) -> None:
    """An admin asking about an org that does not exist gets 404 on every panel."""
    client, _, _ = detail_env
    _admin_id, headers = await create_platform_admin(step_up=False)
    org_id = uuid4()
    for route in ["detail", *SUB_ROUTES]:
        response = await client.get(f"/v1/admin/orgs/{org_id}/{route}", headers=headers)
        assert response.status_code == 404, route


async def test_overview_reports_status_capabilities_and_owners(
    detail_env: tuple[AsyncClient, list[str], _Tracked],
) -> None:
    """The overview carries identity, KYB, lifecycle state, and the owners."""
    client, signed_keys, tracked = detail_env
    seeded = await _seed_org(client, signed_keys, tracked)

    response = await client.get(
        f"/v1/admin/orgs/{seeded.org_id}/detail", headers=seeded.admin_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == seeded.org_id
    assert body["kyb_status"] == "verified"
    assert body["legal_name"] == "Verified Test Org Ltd"
    assert body["registration_number"] == "RC000000"
    # Reinstated, so the suspension record is cleared; history lives in audit.
    assert body["suspended_at"] is None
    assert body["suspended_by"] is None
    assert body["deactivated_by"] is None
    assert body["member_count"] == 2
    assert len(body["owners"]) == 1
    owner = body["owners"][0]
    assert owner["user_id"] == str(seeded.owner_id)
    assert owner["email"].startswith("detail-owner-")
    assert isinstance(body["capabilities"], list)


async def test_overview_shows_suspending_admin(
    detail_env: tuple[AsyncClient, list[str], _Tracked],
) -> None:
    """A suspended org names the admin who suspended it and why."""
    client, _, tracked = detail_env
    admin_id, admin_headers = await create_platform_admin()
    owner_id = await create_user("detail-susp-owner")
    org = await create_org(client, create_access_token(owner_id, []), "suspdetail")
    tracked.org_ids.append(UUID(str(org["id"])))
    await client.post(
        f"/v1/admin/orgs/{org['id']}/suspend",
        json={"reason": "Policy breach recorded by the trust team."},
        headers=admin_headers,
    )

    body = (
        await client.get(f"/v1/admin/orgs/{org['id']}/detail", headers=admin_headers)
    ).json()

    assert body["suspended_at"] is not None
    assert body["suspension_reason"] == "Policy breach recorded by the trust team."
    assert body["suspended_by"]["id"] == str(admin_id)
    assert body["suspended_by"]["display_name"]


async def test_members_lists_roles_teams_and_pending_invitations(
    detail_env: tuple[AsyncClient, list[str], _Tracked],
) -> None:
    """Members carry role and team names; pending invitations are counted."""
    client, signed_keys, tracked = detail_env
    seeded = await _seed_org(client, signed_keys, tracked)

    response = await client.get(
        f"/v1/admin/orgs/{seeded.org_id}/members", headers=seeded.admin_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pending_invitation_count"] == 1
    by_user = {m["user_id"]: m for m in body["members"]}
    assert by_user[str(seeded.owner_id)]["role"] == "owner"
    assert by_user[str(seeded.owner_id)]["teams"] == []
    teamed = by_user[str(seeded.member_user_id)]
    assert teamed["member_id"] == str(seeded.member_id)
    assert teamed["role"] == "member"
    assert [t["name"] for t in teamed["teams"]] == ["Reviewers"]


async def test_verification_presigns_documents_without_raw_keys_and_audits(
    detail_env: tuple[AsyncClient, list[str], _Tracked],
) -> None:
    """KYB documents come back as short-lived signed links, never raw keys.

    Every call writes one ``org_kyb_documents_viewed`` audit row.
    """
    client, signed_keys, tracked = detail_env
    seeded = await _seed_org(client, signed_keys, tracked)

    response = await client.get(
        f"/v1/admin/orgs/{seeded.org_id}/verification", headers=seeded.admin_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["legal_name"] == "Verified Test Org Ltd"
    assert body["kyb_status"] == "verified"
    kinds = sorted(d["kind"] for d in body["documents"])
    assert kinds == ["incorporation", "tax"]
    names = {d["kind"]: d["file_name"] for d in body["documents"]}
    assert names == {"incorporation": "certificate.pdf", "tax": "tax.pdf"}
    assert body["tax_document_type"] == "other"
    assert len(signed_keys) == 2
    for key in signed_keys:
        assert key not in response.text
    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.action == "org_kyb_documents_viewed",
                    AuditLog.target_id == UUID(seeded.org_id),
                )
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].metadata_["document_count"] == 2


async def test_financials_summarises_balances_payouts_and_purchases(
    detail_env: tuple[AsyncClient, list[str], _Tracked],
) -> None:
    """Financials summarise money without exposing payout account details."""
    client, signed_keys, tracked = detail_env
    seeded = await _seed_org(client, signed_keys, tracked)

    response = await client.get(
        f"/v1/admin/orgs/{seeded.org_id}/financials", headers=seeded.admin_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["currency"]
    assert "available_balance" in body and "pending_balance" in body
    assert body["payouts_summary"]["pending_count"] == 0
    assert Decimal(str(body["payouts_summary"]["completed_total"])) == Decimal("100")
    assert body["payouts_summary"]["last_payout_at"] is not None
    assert body["purchases_summary"]["completed_count"] == 1
    assert body["purchases_summary"]["failed_count"] == 1
    assert Decimal(str(body["purchases_summary"]["total_spent"])) == Decimal("199")
    assert len(body["recent_payouts"]) == 1
    assert body["recent_payouts"][0]["provider"] == "paystack"
    assert len(body["recent_transactions"]) == 2
    assert "0123456789" not in response.text
    assert "payout_account" not in response.text


async def test_frameworks_lists_owned_frameworks_and_licenses(
    detail_env: tuple[AsyncClient, list[str], _Tracked],
) -> None:
    """Owned frameworks and held licenses (with grant counts) are listed."""
    client, signed_keys, tracked = detail_env
    seeded = await _seed_org(client, signed_keys, tracked)

    response = await client.get(
        f"/v1/admin/orgs/{seeded.org_id}/frameworks", headers=seeded.admin_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [f["title"] for f in body["frameworks"]] == ["Org Owned Framework"]
    assert len(body["licenses"]) == 1
    held = body["licenses"][0]
    assert held["framework_title"] == "Licensed Framework"
    assert held["license_type"] == "team"
    assert held["grant_count"] == 1


async def test_attestations_lists_in_flight_work(
    detail_env: tuple[AsyncClient, list[str], _Tracked],
) -> None:
    """In-flight attestations name the reviewing member and target title."""
    client, signed_keys, tracked = detail_env
    seeded = await _seed_org(client, signed_keys, tracked)

    response = await client.get(
        f"/v1/admin/orgs/{seeded.org_id}/attestations", headers=seeded.admin_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts"] == {"in_flight": 1, "completed": 0}
    item = body["attestations"][0]
    assert item["status"] == "in_review"
    assert item["target_title"] == "Licensed Framework"
    assert item["reviewing_member_display_name"].startswith("detail-member-")


async def test_audit_returns_org_history_newest_first(
    detail_env: tuple[AsyncClient, list[str], _Tracked],
) -> None:
    """The audit trail shows the suspend and reinstate with resolved actors."""
    client, signed_keys, tracked = detail_env
    seeded = await _seed_org(client, signed_keys, tracked)

    response = await client.get(
        f"/v1/admin/orgs/{seeded.org_id}/audit",
        params={"page": 1, "page_size": 50},
        headers=seeded.admin_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    actions = [item["action"] for item in body["items"]]
    assert actions.index("org_reinstated") < actions.index("org_suspended")
    assert body["total"] >= 2
    assert body["page"] == 1
    suspended = next(i for i in body["items"] if i["action"] == "org_suspended")
    assert suspended["actor"]["display_name"]

    too_big = await client.get(
        f"/v1/admin/orgs/{seeded.org_id}/audit",
        params={"page_size": 101},
        headers=seeded.admin_headers,
    )
    assert too_big.status_code == 422
