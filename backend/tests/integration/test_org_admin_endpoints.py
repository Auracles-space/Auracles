"""Integration tests for admin orgs endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.core.redis import get_redis
from app.core.security import create_access_token
from app.main import app
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


@pytest.fixture
def override_redis() -> Iterator[FakeRedis]:
    """Install a fake Redis for endpoints resolved through get_redis."""
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    yield fake_redis
    app.dependency_overrides.pop(get_redis, None)


async def step_up_platform_admin(admin_id: UUID) -> None:
    """Open a step-up window for ``admin_id`` on the Redis the app resolves.

    Admin org writes sit in the step-up registry, so they read a window rather
    than a code. The window is seeded on whichever fake Redis is currently
    installed for ``get_redis`` — these suites stack more than one override
    fixture, and only the last one installed is the one the route sees.
    """
    await open_step_up_window(app.dependency_overrides[get_redis](), admin_id)


async def create_platform_admin(*, step_up: bool = True) -> tuple[UUID, dict[str, str]]:
    """Create a 2FA-enrolled platform admin and return their headers.

    Opens the admin's step-up window by default so tests reach the write
    itself; pass ``step_up=False`` to exercise the gate.
    """
    admin_id = await create_user("admin", totp_enabled=True)
    if step_up:
        await step_up_platform_admin(admin_id)
    token = create_access_token(admin_id, ["admin"])
    return admin_id, auth(token)


async def test_admin_list_orgs_unauthorized(
    client: AsyncClient, clean_orgs: None, migrated_database: None
) -> None:
    """Non-admins receive 403 Forbidden."""
    user_id = await create_user("user")
    token = create_access_token(user_id, [])
    headers = auth(token)

    res = await client.get("/v1/admin/orgs", headers=headers)
    assert res.status_code == 403


async def test_admin_list_orgs(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """Admin can list orgs and see member counts and capabilities."""
    admin_id, admin_headers = await create_platform_admin()

    owner_id = await create_user("owner")
    owner_token = create_access_token(owner_id, [])

    org = await create_org(client, owner_token, "testorg")
    org_id = org["id"]

    member_id = await create_user("member")
    await add_member(org_id, member_id, "member")

    res = await client.get("/v1/admin/orgs", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1

    found_org = next((o for o in data["orgs"] if o["id"] == org_id), None)
    assert found_org is not None
    assert found_org["name"] == "testorg"
    assert found_org["member_count"] == 2
    assert "can_attest" not in found_org["capabilities"]


async def test_admin_suspend_org(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """Suspending an org needs an open step-up window, then returns 204.

    Suspension removes every member's org access at once, so it sits in the
    step-up registry alongside the other privilege changes.
    """
    admin_id, admin_headers = await create_platform_admin(step_up=False)

    owner_id = await create_user("owner")
    owner_token = create_access_token(owner_id, [])

    org = await create_org(client, owner_token, "targetorg")
    org_id = org["id"]

    no_window = await client.post(
        f"/v1/admin/orgs/{org_id}/suspend",
        json={"reason": "Policy breach recorded by the trust team."},
        headers=admin_headers,
    )
    assert no_window.status_code == 403
    assert no_window.json()["detail"]["error_code"] == "step_up_required"

    await step_up_platform_admin(admin_id)
    res = await client.post(
        f"/v1/admin/orgs/{org_id}/suspend",
        json={"reason": "Policy breach recorded by the trust team."},
        headers=admin_headers,
    )
    assert res.status_code == 204

    res2 = await client.post(
        f"/v1/admin/orgs/{org_id}/suspend",
        json={"reason": "Policy breach recorded by the trust team."},
        headers=admin_headers,
    )
    assert res2.status_code == 204

    patch_res = await client.patch(
        f"/v1/orgs/{org_id}", json={"name": "New Name"}, headers=auth(owner_token)
    )
    assert patch_res.status_code == 403
    assert patch_res.json()["detail"]["error_code"] == "org_suspended"


async def test_orgs_mine_exposes_suspension_state(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """A member's /orgs/mine entry reports suspended_at so the UI can warn."""
    del override_redis
    _admin_id, admin_headers = await create_platform_admin()

    owner_id = await create_user("mine-suspend-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "minesuspendorg")
    org_id = org["id"]

    before = await client.get("/v1/orgs/mine", headers=auth(owner_token))
    entry = next(o for o in before.json()["organizations"] if o["org"]["id"] == org_id)
    assert entry["org"]["suspended_at"] is None

    await client.post(
        f"/v1/admin/orgs/{org_id}/suspend",
        json={"reason": "Policy breach recorded by the trust team."},
        headers=admin_headers,
    )

    after = await client.get("/v1/orgs/mine", headers=auth(owner_token))
    entry = next(o for o in after.json()["organizations"] if o["org"]["id"] == org_id)
    assert entry["org"]["suspended_at"] is not None


async def test_admin_reinstate_org_lifts_suspension(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """Reinstating a suspended org returns 204 and restores org-admin actions."""
    del override_redis
    _admin_id, admin_headers = await create_platform_admin()

    owner_id = await create_user("reinstate-owner")
    owner_token = create_access_token(owner_id, [])

    org = await create_org(client, owner_token, "reinstateorg")
    org_id = org["id"]

    await client.post(
        f"/v1/admin/orgs/{org_id}/suspend",
        json={"reason": "Policy breach recorded by the trust team."},
        headers=admin_headers,
    )

    res = await client.post(f"/v1/admin/orgs/{org_id}/reinstate", headers=admin_headers)
    assert res.status_code == 204

    # Idempotent: reinstating an active org is a no-op.
    res2 = await client.post(
        f"/v1/admin/orgs/{org_id}/reinstate", headers=admin_headers
    )
    assert res2.status_code == 204

    patch_res = await client.patch(
        f"/v1/orgs/{org_id}", json={"name": "New Name"}, headers=auth(owner_token)
    )
    assert patch_res.status_code == 200


async def test_admin_reinstate_org_syncs_derived_roles_for_members(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reinstatement re-evaluates derived roles for every org member."""
    del override_redis
    from app.modules.organizations import service as org_service

    _admin_id, admin_headers = await create_platform_admin()
    owner_id = await create_user("reinstate-sync-owner")
    member_id = await create_user("reinstate-sync-member")
    org = await create_org(
        client, create_access_token(owner_id, []), "reinstatesyncorg"
    )
    await add_member(str(org["id"]), member_id, "member")
    await client.post(
        f"/v1/admin/orgs/{org['id']}/suspend",
        json={"reason": "Policy breach recorded by the trust team."},
        headers=admin_headers,
    )

    synced: list[UUID] = []

    async def record_sync(db: object, *, user_id: UUID) -> None:
        """Record which user ids the reinstatement path syncs."""
        del db
        synced.append(user_id)

    monkeypatch.setattr(org_service, "sync_derived_roles", record_sync)

    res = await client.post(
        f"/v1/admin/orgs/{org['id']}/reinstate", headers=admin_headers
    )

    assert res.status_code == 204
    assert sorted(synced) == sorted([owner_id, member_id])


async def test_admin_list_orgs_reports_total_on_empty_page(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
) -> None:
    """A page beyond the last result still reports the true total count."""
    del override_redis
    _admin_id, admin_headers = await create_platform_admin()
    owner_id = await create_user("pg-owner")
    await create_org(client, create_access_token(owner_id, []), "pgorg")

    res = await client.get("/v1/admin/orgs?page=2&page_size=20", headers=admin_headers)

    assert res.status_code == 200
    data = res.json()
    assert data["orgs"] == []
    assert data["total"] == 1
    assert data["page"] == 2


async def test_admin_suspend_org_syncs_derived_roles_for_members(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Suspension re-evaluates derived roles for every org member."""
    del override_redis
    from app.modules.organizations import service as org_service

    synced: list[UUID] = []

    async def record_sync(db: object, *, user_id: UUID) -> None:
        """Record which user ids the suspension path syncs."""
        del db
        synced.append(user_id)

    monkeypatch.setattr(org_service, "sync_derived_roles", record_sync)
    _admin_id, admin_headers = await create_platform_admin()
    owner_id = await create_user("sync-owner")
    member_id = await create_user("sync-member")
    org = await create_org(client, create_access_token(owner_id, []), "syncorg")
    await add_member(str(org["id"]), member_id, "member")

    res = await client.post(
        f"/v1/admin/orgs/{org['id']}/suspend",
        json={"reason": "Policy breach recorded by the trust team."},
        headers=admin_headers,
    )

    assert res.status_code == 204
    assert sorted(synced) == sorted([owner_id, member_id])


class RecordingDispatch:
    """Capture queued owner notifications instead of hitting Celery."""

    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    def delay(self, **kwargs: object) -> None:
        self.sent.append(kwargs)


def record_owner_notifications(monkeypatch: pytest.MonkeyPatch) -> RecordingDispatch:
    """Swap the org notification dispatcher for an in-memory recorder."""
    from app.modules.organizations import notifications as _notifications

    recorder = RecordingDispatch()
    monkeypatch.setattr(_notifications, "dispatch_project_notification", recorder)
    return recorder


async def test_admin_suspend_org_requires_reason_stores_it_and_notifies_owner(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A suspension carries a reason the owner can read, and the owner hears it.

    Slice 2 decision 1: admins must say why; the reason is stored on the org,
    surfaced on /orgs/mine for the banner, and delivered as a notification.
    Reinstating clears it and notifies again.
    """
    del override_redis
    recorder = record_owner_notifications(monkeypatch)
    _admin_id, admin_headers = await create_platform_admin()

    owner_id = await create_user("reason-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "reasonorg")
    org_id = org["id"]

    missing = await client.post(
        f"/v1/admin/orgs/{org_id}/suspend",
        headers=admin_headers,
    )
    assert missing.status_code == 422

    too_short = await client.post(
        f"/v1/admin/orgs/{org_id}/suspend", json={"reason": "no"}, headers=admin_headers
    )
    assert too_short.status_code == 422

    reason = "Repeated chargebacks on operator purchases."
    res = await client.post(
        f"/v1/admin/orgs/{org_id}/suspend",
        json={"reason": reason},
        headers=admin_headers,
    )
    assert res.status_code == 204

    mine = await client.get("/v1/orgs/mine", headers=auth(owner_token))
    entry = next(o for o in mine.json()["organizations"] if o["org"]["id"] == org_id)
    assert entry["org"]["suspension_reason"] == reason

    suspended = next(
        c for c in recorder.sent if c["notification_type"] == "org_suspended"
    )
    assert suspended["user_id"] == str(owner_id)
    assert reason in str(suspended["body"])
    assert suspended["link"] == f"/dashboard/organizations/{org_id}"

    lifted = await client.post(
        f"/v1/admin/orgs/{org_id}/reinstate", headers=admin_headers
    )
    assert lifted.status_code == 204

    mine = await client.get("/v1/orgs/mine", headers=auth(owner_token))
    entry = next(o for o in mine.json()["organizations"] if o["org"]["id"] == org_id)
    assert entry["org"]["suspended_at"] is None
    assert entry["org"]["suspension_reason"] is None
    assert any(c["notification_type"] == "org_reinstated" for c in recorder.sent)


async def test_admin_capability_suspend_requires_reason_and_notifies_owner(
    client: AsyncClient,
    override_redis: FakeRedis,
    clean_orgs: None,
    migrated_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Suspending a capability records why, exposes it on /orgs/mine, notifies.

    Contributor is used because it self-activates without KYB fixtures; the
    three capability services share the same contract.
    """
    del override_redis
    recorder = record_owner_notifications(monkeypatch)
    _admin_id, admin_headers = await create_platform_admin()

    owner_id = await create_user("cap-reason-owner")
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "capreasonorg")
    org_id = org["id"]
    from tests.conftest import verify_org_kyb

    await verify_org_kyb(org_id)
    activated = await client.post(
        f"/v1/orgs/{org_id}/contributor-capability/activate", headers=auth(owner_token)
    )
    assert activated.status_code in (200, 201), activated.text

    missing = await client.post(
        f"/v1/admin/orgs/{org_id}/contributor-capability/suspend",
        headers=admin_headers,
    )
    assert missing.status_code == 422

    reason = "Framework artifacts failed the malware scan twice."
    res = await client.post(
        f"/v1/admin/orgs/{org_id}/contributor-capability/suspend",
        json={"reason": reason},
        headers=admin_headers,
    )
    assert res.status_code == 204

    mine = await client.get("/v1/orgs/mine", headers=auth(owner_token))
    entry = next(o for o in mine.json()["organizations"] if o["org"]["id"] == org_id)
    assert entry["capabilities"]["contributor"] == "suspended"
    assert entry["capability_reasons"]["contributor"] == reason

    # The admin directory shows the same reason so the next admin knows why.
    listed = await client.get("/v1/admin/orgs", headers=admin_headers)
    row = next(o for o in listed.json()["orgs"] if o["id"] == org_id)
    assert row["capabilities"]["contributor"] == "suspended"
    assert row["capability_reasons"]["contributor"] == reason

    sent = next(
        c for c in recorder.sent if c["notification_type"] == "org_capability_suspended"
    )
    assert sent["user_id"] == str(owner_id)
    assert reason in str(sent["body"])

    lifted = await client.post(
        f"/v1/admin/orgs/{org_id}/contributor-capability/reinstate",
        headers=admin_headers,
    )
    assert lifted.status_code == 204
    mine = await client.get("/v1/orgs/mine", headers=auth(owner_token))
    entry = next(o for o in mine.json()["organizations"] if o["org"]["id"] == org_id)
    assert entry["capabilities"]["contributor"] == "active"
    assert "contributor" not in entry["capability_reasons"]
    assert any(
        c["notification_type"] == "org_capability_reinstated" for c in recorder.sent
    )
