"""Slice B of the organizations rework: the invitation lifecycle.

Invitation history with a live-computed status, resend, invitee-facing
notifications on revoke and expiry, inviter notifications that land on the
members page, a member search that skips closed and suspended accounts, and
the registration ``next`` hand-off that lets an invitee land back on their
invitation after verifying their email.

Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md
§Slice B (invitations).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.security import create_access_token, hash_token
from app.integrations import resend as resend_adapter
from app.modules.auth import service as auth_service
from app.modules.notifications.models import Notification
from app.modules.organizations.models import OrgInvitation
from app.modules.organizations.service import INVITE_RATE_LIMITER
from app.shared.models.audit_log import AuditLog
from app.workers.tasks.organizations_beat import _expire_pending_invitations_impl
from tests.integration.test_auth_sessions import FakeRedis
from tests.integration.test_org_admin_endpoints import (
    RecordingDispatch,
    record_owner_notifications,
)
from tests.integration.test_org_invitations_endpoints import (
    _create_user_with_email,
    _invite,
    invitation_test_context,
    migrated_database,
)
from tests.integration.test_organizations_endpoints import (
    auth,
    create_org,
    create_user,
)
from tests.unit.integrations.test_resend_dispatch import _FakeSettings

pytestmark = pytest.mark.asyncio

__all__ = ["invitation_test_context", "migrated_database"]


def _by_type(recorder: RecordingDispatch, notification_type: str) -> list[dict]:
    """Return every recorded dispatch of one notification type."""
    return [c for c in recorder.sent if c["notification_type"] == notification_type]


async def _set_expiry(invitation_id: str, expires_at: datetime) -> None:
    """Move one invitation's expiry directly."""
    async with async_session_factory() as session:
        async with session.begin():
            row = await session.get(OrgInvitation, UUID(invitation_id))
            assert row is not None
            row.expires_at = expires_at


async def _set_status(invitation_id: str, status: str) -> None:
    """Set one invitation's stored status directly."""
    async with async_session_factory() as session:
        async with session.begin():
            row = await session.get(OrgInvitation, UUID(invitation_id))
            assert row is not None
            row.status = status


# --- (a) history filter with live expiry -----------------------------------------


async def test_list_invitations_filters_by_status_and_computes_expiry(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``?status=`` selects history; a stale pending row reads as ``expired``.

    The nightly sweep flips overdue rows, but an admin looking at the list
    before it runs must not see a dead invitation labelled pending.
    """
    del migrated_database, invitation_test_context
    owner_id = await create_user("hist-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "history")
    base = f"/v1/orgs/{org['id']}/invitations"

    async def invite(email: str) -> str:
        await _invite(client, monkeypatch, org, token, email)
        async with async_session_factory() as session:
            row = await session.scalar(
                select(OrgInvitation).where(OrgInvitation.email == email)
            )
            assert row is not None
            return str(row.id)

    live_id = await invite("live@auracles.space")
    stale_id = await invite("stale@auracles.space")
    declined_id = await invite("declined@auracles.space")
    revoked_id = await invite("revoked@auracles.space")
    await _set_expiry(stale_id, datetime.now(UTC) - timedelta(minutes=1))
    await _set_status(declined_id, "declined")
    await _set_status(revoked_id, "revoked")

    default = await client.get(base, headers=auth(token))
    assert default.status_code == 200
    default_rows = {r["id"]: r for r in default.json()["invitations"]}
    assert set(default_rows) == {live_id}
    assert default_rows[live_id]["status"] == "pending"
    assert default_rows[live_id]["expires_at"]

    expired = await client.get(base, params={"status": "expired"}, headers=auth(token))
    expired_rows = {r["id"]: r for r in expired.json()["invitations"]}
    assert set(expired_rows) == {stale_id}
    assert expired_rows[stale_id]["status"] == "expired"

    declined = await client.get(
        base, params={"status": "declined"}, headers=auth(token)
    )
    assert {r["id"] for r in declined.json()["invitations"]} == {declined_id}

    revoked = await client.get(base, params={"status": "revoked"}, headers=auth(token))
    assert {r["id"] for r in revoked.json()["invitations"]} == {revoked_id}

    everything = await client.get(base, params={"status": "all"}, headers=auth(token))
    all_rows = {r["id"]: r["status"] for r in everything.json()["invitations"]}
    assert all_rows == {
        live_id: "pending",
        stale_id: "expired",
        declined_id: "declined",
        revoked_id: "revoked",
    }

    bad = await client.get(base, params={"status": "bogus"}, headers=auth(token))
    assert bad.status_code == 422


# --- (b) resend --------------------------------------------------------------------


async def test_resend_extends_expiry_resends_email_and_notification_and_audits(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST .../resend pushes the deadline out, re-emails, re-notifies, audits.

    The token is rotated so the earlier email's link stops working — the
    invitee follows the newest message, and a stale link cannot outlive a
    resend.
    """
    del migrated_database, invitation_test_context
    owner_id = await create_user("resend-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "resend")
    invitee_email = f"resend-invitee-{uuid4().hex[:8]}@auracles.space"
    invitee_id = await _create_user_with_email("resend-invitee", invitee_email)
    first_token = await _invite(client, monkeypatch, org, token, invitee_email)
    async with async_session_factory() as session:
        row = await session.scalar(
            select(OrgInvitation).where(OrgInvitation.email == invitee_email)
        )
        assert row is not None
        invitation_id = str(row.id)
    await _set_expiry(invitation_id, datetime.now(UTC) - timedelta(hours=1))

    sent: list[tuple[str, str, str, str]] = []
    from app.workers.tasks import org_notifications

    monkeypatch.setattr(
        org_notifications.send_org_invitation,
        "delay",
        lambda *args: sent.append(args),
    )

    res = await client.post(
        f"/v1/orgs/{org['id']}/invitations/{invitation_id}/resend",
        headers=auth(token),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == invitation_id
    assert body["status"] == "pending"
    assert datetime.fromisoformat(body["expires_at"]) > datetime.now(UTC) + timedelta(
        days=6
    )

    assert len(sent) == 1
    email, org_name, role, new_token = sent[0]
    assert (email, org_name, role) == (invitee_email, org["name"], "member")
    assert new_token != first_token

    async with async_session_factory() as session:
        row = await session.get(OrgInvitation, UUID(invitation_id))
        assert row is not None
        assert row.token_hash == hash_token(new_token)
        assert row.expires_at > datetime.now(UTC) + timedelta(days=6)
        received = (
            await session.scalars(
                select(Notification).where(
                    Notification.user_id == invitee_id,
                    Notification.notification_type == "org_invitation_received",
                )
            )
        ).all()
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "org_invitation_resent",
                AuditLog.target_id == UUID(invitation_id),
            )
        )
    # One from the original invite, one from the resend.
    assert len(received) == 2
    assert audit is not None and audit.actor_id == owner_id


async def test_resend_refuses_non_pending_and_foreign_invitations(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A revoked invitation is 409; another org's invitation is 404."""
    del migrated_database, invitation_test_context
    owner_id = await create_user("resend-guard-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "resendguard")
    other = await create_org(client, token, "resendother")
    await _invite(client, monkeypatch, org, token, "guard@auracles.space")
    async with async_session_factory() as session:
        row = await session.scalar(
            select(OrgInvitation).where(OrgInvitation.email == "guard@auracles.space")
        )
        assert row is not None
        invitation_id = str(row.id)

    foreign = await client.post(
        f"/v1/orgs/{other['id']}/invitations/{invitation_id}/resend",
        headers=auth(token),
    )
    assert foreign.status_code == 404

    await _set_status(invitation_id, "revoked")
    stale = await client.post(
        f"/v1/orgs/{org['id']}/invitations/{invitation_id}/resend",
        headers=auth(token),
    )
    assert stale.status_code == 409


async def test_resend_shares_the_invite_rate_limit(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resends count against the same per-org hourly budget as new invites."""
    del migrated_database
    owner_id = await create_user("resend-rl-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "resendrl")
    await _invite(client, monkeypatch, org, token, "rl@auracles.space")
    async with async_session_factory() as session:
        row = await session.scalar(
            select(OrgInvitation).where(OrgInvitation.email == "rl@auracles.space")
        )
        assert row is not None
        invitation_id = str(row.id)
    for _ in range(INVITE_RATE_LIMITER.limit - 1):
        await INVITE_RATE_LIMITER.check(invitation_test_context, org["id"])

    throttled = await client.post(
        f"/v1/orgs/{org['id']}/invitations/{invitation_id}/resend",
        headers=auth(token),
    )
    assert throttled.status_code == 429


# --- (c) invitee hears about revoke and expiry --------------------------------------


async def test_revoke_notifies_invitee_with_an_account(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revoking tells the invitee (when they have an account) the offer is gone."""
    del migrated_database, invitation_test_context
    recorder = record_owner_notifications(monkeypatch)
    owner_id = await create_user("revoke-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "revokeorg")
    invitee_email = f"revoke-invitee-{uuid4().hex[:8]}@auracles.space"
    invitee_id = await _create_user_with_email("revoke-invitee", invitee_email)
    await _invite(client, monkeypatch, org, token, invitee_email)
    async with async_session_factory() as session:
        row = await session.scalar(
            select(OrgInvitation).where(OrgInvitation.email == invitee_email)
        )
        assert row is not None
        invitation_id = str(row.id)

    res = await client.delete(
        f"/v1/orgs/{org['id']}/invitations/{invitation_id}", headers=auth(token)
    )
    assert res.status_code == 204

    revoked = _by_type(recorder, "org_invitation_revoked")
    assert [c["user_id"] for c in revoked] == [str(invitee_id)]
    assert org["name"] in str(revoked[0]["title"]) + str(revoked[0]["body"])


async def test_expiry_sweep_notifies_invitees_with_accounts(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The nightly sweep tells an invitee with an account that the offer lapsed."""
    del migrated_database, invitation_test_context
    recorder = record_owner_notifications(monkeypatch)
    owner_id = await create_user("sweep-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "sweeporg")
    known_email = f"sweep-known-{uuid4().hex[:8]}@auracles.space"
    known_id = await _create_user_with_email("sweep-known", known_email)
    await _invite(client, monkeypatch, org, token, known_email)
    await _invite(client, monkeypatch, org, token, "sweep-stranger@auracles.space")
    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(OrgInvitation).where(OrgInvitation.org_id == UUID(org["id"]))
            )
        ).all()
    for row in rows:
        await _set_expiry(str(row.id), datetime.now(UTC) - timedelta(minutes=5))

    result = await _expire_pending_invitations_impl()

    assert result == {"expired_count": 2}
    expired = _by_type(recorder, "org_invitation_expired")
    assert [c["user_id"] for c in expired] == [str(known_id)]
    assert org["name"] in str(expired[0]["title"]) + str(expired[0]["body"])


# --- (d) inviter notifications link to the members page ----------------------------


async def test_accept_and_decline_notify_inviter_on_the_members_page(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept/decline notifications carry the org members link, not settings."""
    del migrated_database, invitation_test_context
    owner_id = await create_user("link-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "linkorg")
    members_link = f"/dashboard/organizations/{org['id']}/members"

    accept_email = f"link-accept-{uuid4().hex[:8]}@auracles.space"
    accept_raw = await _invite(client, monkeypatch, org, token, accept_email)
    accepter_id = await _create_user_with_email("accepter", accept_email)
    accepted = await client.post(
        f"/v1/org-invitations/{accept_raw}/accept",
        headers=auth(create_access_token(accepter_id, [])),
    )
    assert accepted.status_code == 200, accepted.text

    decline_email = f"link-decline-{uuid4().hex[:8]}@auracles.space"
    decline_raw = await _invite(client, monkeypatch, org, token, decline_email)
    decliner_id = await _create_user_with_email("decliner", decline_email)
    declined = await client.post(
        f"/v1/org-invitations/{decline_raw}/decline",
        headers=auth(create_access_token(decliner_id, [])),
    )
    assert declined.status_code == 204, declined.text

    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(Notification).where(
                    Notification.user_id == owner_id,
                    Notification.notification_type.in_(
                        ["org_invitation_accepted", "org_invitation_declined"]
                    ),
                )
            )
        ).all()
    by_type = {row.notification_type: row for row in rows}
    assert set(by_type) == {"org_invitation_accepted", "org_invitation_declined"}
    assert by_type["org_invitation_accepted"].link == members_link
    assert by_type["org_invitation_declined"].link == members_link


# --- (e) member search skips closed and suspended accounts --------------------------


async def test_member_search_excludes_deactivated_and_suspended_users(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
) -> None:
    """A closed or suspended account never appears as an invite suggestion."""
    del migrated_database, invitation_test_context
    owner_id = await create_user("search-owner")
    token = create_access_token(owner_id, [])
    org = await create_org(client, token, "searchorg")
    stem = f"zq{uuid4().hex[:6]}"
    active_id = await _create_user_with_email(
        f"{stem}-active", f"{stem}-active@auracles.space"
    )
    closed_id = await _create_user_with_email(
        f"{stem}-closed", f"{stem}-closed@auracles.space"
    )
    suspended_id = await _create_user_with_email(
        f"{stem}-suspended", f"{stem}-suspended@auracles.space"
    )
    from app.modules.auth.models import User

    async with async_session_factory() as session:
        async with session.begin():
            closed = await session.get(User, closed_id)
            suspended = await session.get(User, suspended_id)
            assert closed is not None and suspended is not None
            closed.deactivated_at = datetime.now(UTC)
            suspended.suspended_at = datetime.now(UTC)

    res = await client.get(
        f"/v1/orgs/{org['id']}/member-search",
        params={"q": stem},
        headers=auth(token),
    )

    assert res.status_code == 200, res.text
    assert [r["user_id"] for r in res.json()["results"]] == [str(active_id)]


# --- Register ``next`` hand-off ----------------------------------------------------


class _RecordingVerificationTask:
    """Capture verification-email dispatches including the ``next`` path."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def delay(self, *args: Any) -> None:
        self.calls.append(args)


@pytest.mark.parametrize("bad_next", ["https://evil.example", "//evil", "x" * 501])
async def test_register_rejects_unsafe_next(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
    bad_next: str,
) -> None:
    """``next`` must be an in-app path: one leading slash, at most 500 chars."""
    del migrated_database, invitation_test_context
    monkeypatch.setattr(
        auth_service, "send_verification_email", _RecordingVerificationTask()
    )

    res = await client.post(
        "/v1/auth/register",
        json={
            "email": f"next-{uuid4().hex[:8]}@auracles.space",
            "password": "CorrectHorse9",
            "display_name": "Next User",
            "roles": ["operator"],
            "next": bad_next,
        },
    )

    assert res.status_code == 422


async def test_register_threads_next_into_the_verification_email(
    client: AsyncClient,
    migrated_database: None,
    invitation_test_context: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid ``next`` rides along to the verification email task."""
    del migrated_database, invitation_test_context
    recorder = _RecordingVerificationTask()
    monkeypatch.setattr(auth_service, "send_verification_email", recorder)
    email = f"next-ok-{uuid4().hex[:8]}@auracles.space"

    res = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "CorrectHorse9",
            "display_name": "Next User",
            "roles": ["operator"],
            "next": "/org-invitations/abc123",
        },
    )

    assert res.status_code == 200, res.text
    assert len(recorder.calls) == 1
    assert recorder.calls[0][0] == email
    assert recorder.calls[0][2] == "/org-invitations/abc123"


async def test_verification_email_link_carries_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The emailed link becomes ``/verify-email?token=...&next=<urlencoded>``.

    The href is HTML-escaped by the renderer, so the ``&`` reads ``&amp;``.
    """
    captured: dict[str, Any] = {}
    monkeypatch.setattr(resend_adapter, "_dispatch", captured.update)
    monkeypatch.setattr(
        resend_adapter, "get_settings", lambda: _FakeSettings(email_send_enabled=True)
    )

    resend_adapter.send_verification_email(
        "user@auracles.space", "ev_TOKEN123", next_path="/org-invitations/abc?x=1"
    )

    html = str(captured.get("html", ""))
    expected = "/verify-email?token=ev_TOKEN123&next=%2Forg-invitations%2Fabc%3Fx%3D1"
    assert escape(expected) in html


async def test_verification_email_link_omits_next_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``next`` the link is unchanged."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(resend_adapter, "_dispatch", captured.update)
    monkeypatch.setattr(
        resend_adapter, "get_settings", lambda: _FakeSettings(email_send_enabled=True)
    )

    resend_adapter.send_verification_email("user@auracles.space", "ev_TOKEN123")

    html = str(captured.get("html", ""))
    assert "/verify-email?token=ev_TOKEN123" in html
    assert "next=" not in html
