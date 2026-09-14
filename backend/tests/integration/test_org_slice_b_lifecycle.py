"""Slice B of the organizations rework: the owner journey end to end.

Decision 2 (invite anytime): members, invitations, member search and teams
are open before business verification. Decision 4 (soft close, admin can
reopen): deactivation is blocked while money is pending, records who closed
the org and why, tells every member, and an admin can reactivate. Creation,
profile edits and KYB submission each leave a notification behind.

Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md
§Decisions 2 and 4, §Slice B.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.modules.financials.models import Escrow, Payout, PayoutAccount, Transaction
from app.modules.organizations.models import Organization, OrgLegalProfile
from app.shared.models.audit_log import AuditLog
from tests.conftest import open_step_up_window
from tests.integration.test_auth_sessions import FakeRedis
from tests.integration.test_org_admin_endpoints import (
    RecordingDispatch,
    create_platform_admin,
    record_owner_notifications,
)
from tests.integration.test_org_financials_endpoints import _org_payout_account
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


@pytest.fixture
async def clean_money(clean_orgs: FakeRedis) -> AsyncIterator[FakeRedis]:
    """Unwind money rows that reference organizations before ``clean_orgs`` does.

    Transactions, escrows and payouts point at ``organizations``; leaving them
    behind makes the org delete in ``clean_orgs`` fail on the foreign key.
    """

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(Escrow))
            await session.execute(delete(Payout))
            await session.execute(delete(PayoutAccount))
            await session.execute(delete(Transaction))
            await session.commit()

    await cleanup()
    try:
        yield clean_orgs
    finally:
        await cleanup()


def _by_type(recorder: RecordingDispatch, notification_type: str) -> list[dict]:
    """Return every recorded dispatch of one notification type."""
    return [c for c in recorder.sent if c["notification_type"] == notification_type]


async def _org_row(org_id: str) -> Organization:
    """Reload one organization row outside the request session."""
    async with async_session_factory() as session:
        org = await session.get(Organization, UUID(org_id))
        assert org is not None
        return org


# --- Decision 2: invite anytime -----------------------------------------------


async def test_unverified_owner_can_manage_people(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Members, invitations, member search and teams work before verification.

    Decision 2: an owner staffs the organization from day one; only the
    capabilities stay behind business verification.
    """
    del migrated_database, clean_orgs
    from app.workers.tasks import org_notifications

    monkeypatch.setattr(org_notifications.send_org_invitation, "delay", lambda *a: None)
    owner_id = await create_user("unverified-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "shell", verified=False)
    base = f"/v1/orgs/{org['id']}"

    members = await client.get(f"{base}/members", headers=auth(token))
    invited = await client.post(
        f"{base}/invitations",
        json={"email": "newhire@auracles.space", "role": "member"},
        headers=auth(token),
    )
    listed = await client.get(f"{base}/invitations", headers=auth(token))
    searched = await client.get(
        f"{base}/member-search", params={"q": "new"}, headers=auth(token)
    )
    team = await client.post(
        f"{base}/teams", json={"name": "Reviewers"}, headers=auth(token)
    )
    teams = await client.get(f"{base}/teams", headers=auth(token))

    assert members.status_code == 200, members.text
    assert invited.status_code == 201, invited.text
    assert listed.status_code == 200, listed.text
    assert searched.status_code == 200, searched.text
    assert team.status_code == 201, team.text
    assert teams.status_code == 200, teams.text

    # Capabilities remain gated on business verification.
    activate = await client.post(
        f"{base}/contributor-capability/activate", headers=auth(token)
    )
    assert activate.status_code == 403
    assert activate.json()["detail"]["error_code"] == "org_kyb_required"


# --- Profile edits are audited and other owners hear about them -----------------


async def test_update_profile_audits_field_names_and_notifies_the_owner(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATCH writes an ``org_profile_updated`` audit row and tells the owner.

    An org admin edits the profile; the audit row carries the names of the
    fields that changed, never their values, and the owner (who did not make
    the edit) is notified.
    """
    del migrated_database, clean_orgs
    recorder = record_owner_notifications(monkeypatch)
    owner_id = await create_user("edit-owner")
    actor_id = await create_user("edit-admin")
    org = await create_org(client, create_access_token(owner_id, []), "editable")
    await add_member(org["id"], actor_id, "admin")
    token = create_access_token(actor_id, [])

    res = await client.patch(
        f"/v1/orgs/{org['id']}",
        json={"name": "Renamed Org", "website": "https://renamed.example.com"},
        headers=auth(token),
    )
    assert res.status_code == 200, res.text

    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "org_profile_updated",
                AuditLog.target_id == UUID(org["id"]),
            )
        )
    assert audit is not None
    assert audit.actor_id == actor_id
    assert sorted(audit.metadata_["fields"]) == ["name", "website"]
    assert "Renamed Org" not in str(audit.metadata_)

    updates = _by_type(recorder, "org_profile_updated")
    assert [c["user_id"] for c in updates] == [str(owner_id)]
    assert updates[0]["link"] == f"/dashboard/organizations/{org['id']}"
    assert "name" in str(updates[0]["body"]) and "website" in str(updates[0]["body"])


async def test_owner_editing_own_profile_is_not_notified(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The acting owner is skipped: the audit row is written, no notification."""
    del migrated_database, clean_orgs
    recorder = record_owner_notifications(monkeypatch)
    owner_id = await create_user("self-edit-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "selfedit")

    res = await client.patch(
        f"/v1/orgs/{org['id']}", json={"description": "New blurb."}, headers=auth(token)
    )
    assert res.status_code == 200

    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "org_profile_updated")
        )
    assert audit is not None and audit.metadata_["fields"] == ["description"]
    assert _by_type(recorder, "org_profile_updated") == []


async def test_update_profile_with_no_change_is_silent(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A PATCH that changes nothing writes no audit row and sends nothing."""
    del migrated_database, clean_orgs
    recorder = record_owner_notifications(monkeypatch)
    owner_id = await create_user("noop-owner")
    actor_id = await create_user("noop-admin")
    org = await create_org(client, create_access_token(owner_id, []), "unchanged")
    await add_member(org["id"], actor_id, "admin")
    token = create_access_token(actor_id, [])

    res = await client.patch(
        f"/v1/orgs/{org['id']}", json={"name": "unchanged"}, headers=auth(token)
    )
    assert res.status_code == 200

    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "org_profile_updated")
        )
    assert audit is None
    assert _by_type(recorder, "org_profile_updated") == []


# --- Decision 4: soft close ------------------------------------------------------


async def test_deactivate_blocked_while_money_is_pending(
    client: AsyncClient,
    migrated_database: None,
    clean_money: FakeRedis,
) -> None:
    """A pending transaction, held escrow, or in-flight payout blocks closing.

    Closing an organization with money in motion would orphan the funds; the
    409 names the block so the owner knows what to settle first.
    """
    del migrated_database, clean_money
    owner_id = await create_user("money-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "moneyorg")
    org_id = UUID(org["id"])

    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_org_id=org_id,
                amount=Decimal("100.00"),
                net_amount=Decimal("90.00"),
                transaction_type="purchase",
                status="pending",
            )
            session.add(transaction)

    blocked = await client.delete(f"/v1/orgs/{org_id}", headers=auth(token))
    assert blocked.status_code == 409, blocked.text
    assert "pending" in blocked.json()["detail"].lower()

    async with async_session_factory() as session:
        async with session.begin():
            transaction = await session.scalar(
                select(Transaction).where(Transaction.payer_org_id == org_id)
            )
            assert transaction is not None
            transaction.status = "completed"
            session.add(
                Escrow(
                    ref_id=org_id,
                    ref_type="milestone",
                    amount=Decimal("100.00"),
                    status="held",
                    transaction_id=transaction.id,
                )
            )

    blocked = await client.delete(f"/v1/orgs/{org_id}", headers=auth(token))
    assert blocked.status_code == 409, blocked.text

    async with async_session_factory() as session:
        async with session.begin():
            escrow = await session.scalar(select(Escrow))
            assert escrow is not None
            escrow.status = "released"
    account_id = await _org_payout_account(org_id)
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Payout(
                    org_id=org_id,
                    payout_account_id=account_id,
                    amount=Decimal("50.00"),
                    commission_deducted=Decimal("0"),
                    net_amount=Decimal("50.00"),
                    status="processing",
                )
            )

    blocked = await client.delete(f"/v1/orgs/{org_id}", headers=auth(token))
    assert blocked.status_code == 409, blocked.text

    async with async_session_factory() as session:
        async with session.begin():
            payout = await session.scalar(select(Payout))
            assert payout is not None
            payout.status = "completed"

    closed = await client.delete(f"/v1/orgs/{org_id}", headers=auth(token))
    assert closed.status_code == 204, closed.text


async def test_deactivate_records_actor_and_reason_and_notifies_every_member(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE stores who closed the org and why, and every member is told.

    The notification says the organization is closed and hidden, that its
    data is retained, and who to contact — so a member who finds the org
    gone from their dashboard is not left guessing.
    """
    del migrated_database, clean_orgs
    recorder = record_owner_notifications(monkeypatch)
    owner_id = await create_user("close-owner")
    member_id = await create_user("close-member")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "closing")
    await add_member(org["id"], member_id, "member")

    res = await client.request(
        "DELETE",
        f"/v1/orgs/{org['id']}",
        json={"reason": "Winding down the consultancy."},
        headers=auth(token),
    )
    assert res.status_code == 204, res.text

    row = await _org_row(org["id"])
    assert row.deactivated_at is not None
    assert row.deactivated_by == owner_id
    assert row.deactivation_reason == "Winding down the consultancy."

    closed = _by_type(recorder, "org_deactivated")
    assert sorted(c["user_id"] for c in closed) == sorted(
        [str(owner_id), str(member_id)]
    )
    body = str(closed[0]["body"]).lower()
    assert "closed" in body and "hidden" in body and "retained" in body
    assert "winding down the consultancy" in body
    assert closed[0]["link"] == "/dashboard/organizations"


async def test_deactivate_reason_is_optional_and_bounded(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The body is optional; a reason over 500 characters is refused."""
    del migrated_database, clean_orgs
    record_owner_notifications(monkeypatch)
    owner_id = await create_user("optional-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "optional")

    too_long = await client.request(
        "DELETE",
        f"/v1/orgs/{org['id']}",
        json={"reason": "x" * 501},
        headers=auth(token),
    )
    assert too_long.status_code == 422

    bare = await client.delete(f"/v1/orgs/{org['id']}", headers=auth(token))
    assert bare.status_code == 204, bare.text
    row = await _org_row(org["id"])
    assert row.deactivated_by == owner_id
    assert row.deactivation_reason is None


async def test_admin_reactivate_reopens_and_notifies_owners(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /v1/admin/orgs/{id}/reactivate is admin + step-up and reopens the org.

    Reactivation clears the closure record, writes ``org_reactivated`` to the
    audit log, tells the owners, and the org is back on their dashboard.
    """
    del migrated_database
    recorder = record_owner_notifications(monkeypatch)
    owner_id = await create_user("reopen-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "reopen")
    org_id = org["id"]
    closed = await client.request(
        "DELETE", f"/v1/orgs/{org_id}", json={"reason": "Pause."}, headers=auth(token)
    )
    assert closed.status_code == 204

    path = f"/v1/admin/orgs/{org_id}/reactivate"
    as_owner = await client.post(path, headers=auth(token))
    assert as_owner.status_code == 403

    cold_admin_id, cold_headers = await create_platform_admin(step_up=False)
    without_window = await client.post(path, headers=cold_headers)
    assert without_window.status_code == 403
    assert without_window.json()["detail"]["error_code"] == "step_up_required"

    await open_step_up_window(clean_orgs, cold_admin_id)
    reopened = await client.post(path, headers=cold_headers)
    assert reopened.status_code == 204, reopened.text

    row = await _org_row(org_id)
    assert row.deactivated_at is None
    assert row.deactivated_by is None
    assert row.deactivation_reason is None

    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "org_reactivated",
                AuditLog.target_id == UUID(org_id),
            )
        )
    assert audit is not None and audit.actor_id == cold_admin_id

    reactivated = _by_type(recorder, "org_reactivated")
    assert [c["user_id"] for c in reactivated] == [str(owner_id)]
    assert reactivated[0]["link"] == f"/dashboard/organizations/{org_id}"

    mine = await client.get("/v1/orgs/mine", headers=auth(token))
    assert org_id in {o["org"]["id"] for o in mine.json()["organizations"]}

    # Reopening an open org is a no-op, not an error.
    again = await client.post(path, headers=cold_headers)
    assert again.status_code == 204
    assert len(_by_type(recorder, "org_reactivated")) == 1


async def test_admin_directory_exposes_lifecycle_actors_and_reasons(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The admin org list carries who suspended/closed the org and why."""
    del migrated_database, clean_orgs
    record_owner_notifications(monkeypatch)
    admin_id, admin_headers = await create_platform_admin()
    owner_id = await create_user("dir-owner")
    token = create_access_token(owner_id, [])
    suspended = await create_org(client, token, "dir-suspended")
    closed = await create_org(client, token, "dir-closed")

    res = await client.post(
        f"/v1/admin/orgs/{suspended['id']}/suspend",
        json={"reason": "Chargeback pattern under review."},
        headers=admin_headers,
    )
    assert res.status_code == 204
    res = await client.request(
        "DELETE",
        f"/v1/orgs/{closed['id']}",
        json={"reason": "Merged into another entity."},
        headers=auth(token),
    )
    assert res.status_code == 204

    listing = await client.get("/v1/admin/orgs", headers=admin_headers)
    assert listing.status_code == 200
    by_id = {o["id"]: o for o in listing.json()["orgs"]}

    assert by_id[suspended["id"]]["suspended_by"] == str(admin_id)
    assert (
        by_id[suspended["id"]]["suspension_reason"]
        == "Chargeback pattern under review."
    )
    assert by_id[suspended["id"]]["deactivated_by"] is None
    assert by_id[closed["id"]]["deactivated_by"] == str(owner_id)
    assert by_id[closed["id"]]["deactivation_reason"] == "Merged into another entity."
    assert by_id[closed["id"]]["suspended_by"] is None

    lifted = await client.post(
        f"/v1/admin/orgs/{suspended['id']}/reinstate", headers=admin_headers
    )
    assert lifted.status_code == 204
    row = await _org_row(suspended["id"])
    assert row.suspended_by is None and row.suspension_reason is None


# --- Creation and KYB submission acknowledgements --------------------------------


async def test_create_org_notifies_the_creator(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /v1/orgs leaves an ``org_created`` notification linking to the org."""
    del migrated_database, clean_orgs
    recorder = record_owner_notifications(monkeypatch)
    user_id = await create_user("create-ack")
    token = create_access_token(user_id, [])

    org = await create_org(client, token, "acmestudio", verified=False)

    created = _by_type(recorder, "org_created")
    assert [c["user_id"] for c in created] == [str(user_id)]
    assert "acmestudio" in str(created[0]["title"]) + str(created[0]["body"])
    assert created[0]["link"] == f"/dashboard/organizations/{org['id']}"


async def test_kyb_submit_acknowledges_the_submitting_owner(
    client: AsyncClient,
    migrated_database: None,
    clean_orgs: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Submitting business verification tells the submitter it is in review."""
    del migrated_database
    recorder = record_owner_notifications(monkeypatch)
    from app.modules.organizations import kyb_service as _svc

    monkeypatch.setattr(_svc, "notify_admins_review_pending", lambda **kwargs: None)
    owner_id = await create_user("kyb-ack", totp_enabled=True)
    await open_step_up_window(clean_orgs, owner_id)
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "kybackorg", verified=False)
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgLegalProfile(
                    org_id=UUID(org["id"]),
                    legal_name="KYB Ack Ltd",
                    registration_number="RC123456",
                    incorporation_doc_keys=["org-incorporation-docs/x/cert.pdf"],
                    kyb_status="unverified",
                )
            )

    res = await client.post(f"/v1/orgs/{org['id']}/kyb/submit", headers=auth(token))
    assert res.status_code == 200, res.text

    submitted = _by_type(recorder, "org_kyb_submitted")
    assert [c["user_id"] for c in submitted] == [str(owner_id)]
    assert "in review" in str(submitted[0]["body"]).lower()
    assert "notify you" in str(submitted[0]["body"]).lower()
    assert submitted[0]["link"] == f"/dashboard/organizations/{org['id']}/verification"
