"""Integration tests for org License grants when a member is removed.

``license_grants.member_id`` cascades on delete, so removing a member would
otherwise silently drop their shared-library access with no audit trail.
Removal must revoke each grant explicitly, audit it against the remover,
and tell the member their shared library access ended.

Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md
§Slice A.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.frameworks.models import LicenseGrant
from app.shared.models.audit_log import AuditLog
from tests.integration.test_org_library_endpoints import (
    _add_member,
    _auth_headers,
    _create_framework_snapshot,
    _create_org,
    _create_user,
    _grant_org_license,
    migrated_database,  # noqa: F401 - pytest fixture reuse
    org_library_context,  # noqa: F401 - pytest fixture reuse
)

pytestmark = pytest.mark.asyncio


def _record_org_notifications(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, object]]:
    """Capture org notifications queued through the shared helper."""
    from app.modules.organizations import notifications as _notifications

    sent: list[dict[str, object]] = []

    class _Recorder:
        def delay(self, **kwargs: object) -> None:
            sent.append(kwargs)

    monkeypatch.setattr(_notifications, "dispatch_project_notification", _Recorder())
    return sent


async def _add_member_grant(license_id: UUID, member_id: UUID) -> UUID:
    """Insert one direct member grant row and return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            grant = LicenseGrant(license_id=license_id, member_id=member_id)
            session.add(grant)
            await session.flush()
            return grant.id


async def _grant_ids_for_member(member_id: UUID) -> list[UUID]:
    """Return every grant id still held by one member row."""
    async with async_session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(LicenseGrant.id).where(LicenseGrant.member_id == member_id)
                )
            ).all()
        )


async def _revocation_audits() -> list[AuditLog]:
    """Return every ``license_grant_revoked`` audit row, oldest first."""
    async with async_session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(AuditLog)
                    .where(AuditLog.action == "license_grant_revoked")
                    .order_by(AuditLog.created_at)
                )
            ).all()
        )


async def test_removing_member_revokes_grants_with_audit_and_notice(
    client: AsyncClient,
    migrated_database: None,  # noqa: F811 - pytest fixture reuse
    org_library_context: dict[str, object],  # noqa: F811 - pytest fixture reuse
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing a member writes one audit row per revoked grant and says so.

    Each ``license_grant_revoked`` row names the remover as actor and carries
    ``{"reason": "member_removed"}``; another member's grants are untouched;
    the removed member's notification mentions that shared library access
    ended.
    """
    del migrated_database, org_library_context
    sent = _record_org_notifications(monkeypatch)
    contributor_id = await _create_user("removal-seller")
    owner_id = await _create_user("removal-owner")
    member_user_id = await _create_user("removal-member")
    other_user_id = await _create_user("removal-other")
    org = await _create_org(client, owner_id, "removal")
    org_id = UUID(org["id"])
    member_id = await _add_member(org_id, member_user_id)
    other_member_id = await _add_member(org_id, other_user_id)
    framework_a, _ = await _create_framework_snapshot(contributor_id)
    framework_b, _ = await _create_framework_snapshot(contributor_id)
    license_a = await _grant_org_license(framework_a, org_id)
    license_b = await _grant_org_license(framework_b, org_id)
    await _add_member_grant(license_a, member_id)
    await _add_member_grant(license_b, member_id)
    other_grant_id = await _add_member_grant(license_a, other_member_id)

    response = await client.delete(
        f"/v1/orgs/{org_id}/members/{member_id}",
        headers=_auth_headers(owner_id),
    )

    assert response.status_code == 204
    assert await _grant_ids_for_member(member_id) == []
    assert await _grant_ids_for_member(other_member_id) == [other_grant_id]

    audits = await _revocation_audits()
    assert len(audits) == 2
    assert {audit.target_id for audit in audits} == {license_a, license_b}
    for audit in audits:
        assert audit.actor_id == owner_id
        assert audit.target_type == "license"
        assert audit.metadata_["reason"] == "member_removed"
        assert audit.metadata_["org_id"] == str(org_id)
        assert audit.metadata_["member_id"] == str(member_id)

    note = next(c for c in sent if c["notification_type"] == "org_member_removed")
    assert note["user_id"] == str(member_user_id)
    assert "shared library" in str(note["body"])


async def test_removing_member_without_grants_writes_no_revocation_audit(
    client: AsyncClient,
    migrated_database: None,  # noqa: F811 - pytest fixture reuse
    org_library_context: dict[str, object],  # noqa: F811 - pytest fixture reuse
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A member holding no grants is removed with the plain notice and no audit."""
    del migrated_database, org_library_context
    sent = _record_org_notifications(monkeypatch)
    owner_id = await _create_user("nogrant-owner")
    member_user_id = await _create_user("nogrant-member")
    org = await _create_org(client, owner_id, "nogrant")
    org_id = UUID(org["id"])
    member_id = await _add_member(org_id, member_user_id)

    response = await client.delete(
        f"/v1/orgs/{org_id}/members/{member_id}",
        headers=_auth_headers(owner_id),
    )

    assert response.status_code == 204
    assert await _revocation_audits() == []
    note = next(c for c in sent if c["notification_type"] == "org_member_removed")
    assert "shared library" not in str(note["body"])
