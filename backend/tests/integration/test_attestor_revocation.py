"""Integration tests for what revoking an org's attestor capability does to its work.

A revoked org must not hold requestors up or keep producing reports. Its open
offers are withdrawn and the request moves on to the next eligible org; reviews
it has not delivered yet go to admins to reassign. Reviews whose report is
already in (submitted or disputed) stay put so the requestor and admins can
finish them. Suspension is temporary and changes none of this.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.attestation import notifications
from app.modules.attestation.models import Attestation, AttestationOffer
from app.modules.organizations import attestor_application_service
from app.shared.models.audit_log import AuditLog
from tests.integration.test_attestation_matching import (  # noqa: F401
    FakeNotificationTask,
    create_admin_user,
    create_org_attestor,
    create_user,
    matching_context,
    migrated_database,
)

pytestmark = pytest.mark.usefixtures("migrated_database", "matching_context")


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    """Capture user notifications and admin review notices."""
    captured: dict[str, list[dict[str, Any]]] = {"users": [], "admins": []}
    monkeypatch.setattr(
        notifications,
        "dispatch_project_notification",
        FakeNotificationTask(captured["users"]),
    )
    monkeypatch.setattr(
        notifications,
        "notify_admins_review_pending",
        lambda **kwargs: captured["admins"].append(kwargs),
    )
    return captured


async def _attestation(requestor_id: UUID, status: str) -> UUID:
    """Create a funded operator-target Attestation matching healthcare/US orgs."""
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="operator",
                target_id=requestor_id,
                requestor_id=requestor_id,
                status=status,
                requested_specializations=["healthcare"],
                requested_jurisdictions=["US"],
                fee_amount=Decimal("300.00"),
                currency="USD",
            )
            session.add(attestation)
            await session.flush()
            return attestation.id


async def _offer(attestation_id: UUID, org_id: UUID, status: str) -> UUID:
    """Attach a cohort-0 offer for one org."""
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            offer = AttestationOffer(
                attestation_id=attestation_id,
                org_id=org_id,
                cohort_index=0,
                status=status,
                offered_at=now,
                expires_at=now + timedelta(hours=48),
            )
            session.add(offer)
            await session.flush()
            return offer.id


async def _assign(attestation_id: UUID, org_id: UUID, member_id: UUID) -> None:
    """Staff an Attestation to an org member as an accepted offer would."""
    await _offer(attestation_id, org_id, "accepted")
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            attestation = await session.get(Attestation, attestation_id)
            assert attestation is not None
            attestation.attestor_org_id = org_id
            attestation.reviewing_member_id = member_id
            attestation.accepted_at = now
            attestation.completion_due_at = now + timedelta(days=7)


async def _set_capability(org_id: UUID, status_value: str) -> None:
    """Change the org's attestor capability as a platform admin."""
    admin_id = await create_admin_user()
    async with async_session_factory() as session:
        await attestor_application_service.admin_set_capability_status(
            session,
            org_id=org_id,
            admin_id=admin_id,
            status_value=status_value,  # type: ignore[arg-type]
            reason="Calibration drift after two upheld disputes.",
        )


async def _offers(attestation_id: UUID) -> set[tuple[UUID, str, int]]:
    """Return (org, status, cohort) for every offer on an Attestation."""
    async with async_session_factory() as session:
        rows = await session.execute(
            select(
                AttestationOffer.org_id,
                AttestationOffer.status,
                AttestationOffer.cohort_index,
            ).where(AttestationOffer.attestation_id == attestation_id)
        )
        return {(row[0], row[1], row[2]) for row in rows.all()}


async def _load(attestation_id: UUID) -> Attestation:
    """Reload an Attestation."""
    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)
        assert attestation is not None
        return attestation


async def test_revocation_withdraws_open_offers_and_offers_the_next_org(
    sent: dict[str, list[dict[str, Any]]],
) -> None:
    """The requestor is not left waiting on an offer the org can never answer."""
    requestor_id = await create_user("revoke-requestor@auracles.space", ["operator"])
    revoked_org, _, _ = await create_org_attestor(
        specializations=["healthcare"], jurisdictions=["US"], slug_prefix="revoked"
    )
    next_org, next_owner, _ = await create_org_attestor(
        specializations=["healthcare"], jurisdictions=["US"], slug_prefix="next"
    )
    attestation_id = await _attestation(requestor_id, "offered")
    await _offer(attestation_id, revoked_org, "offered")

    await _set_capability(revoked_org, "revoked")

    assert await _offers(attestation_id) == {
        (revoked_org, "superseded", 0),
        (next_org, "offered", 1),
    }
    assert (await _load(attestation_id)).status == "offered"
    received = [
        call
        for call in sent["users"]
        if call["notification_type"] == "attestation_offer_received"
    ]
    assert [call["user_id"] for call in received] == [str(next_owner)]


async def test_revocation_sends_the_request_to_admins_when_no_org_is_left(
    sent: dict[str, list[dict[str, Any]]],
) -> None:
    """With nobody else eligible, matching hands the request to an admin."""
    requestor_id = await create_user("revoke-alone@auracles.space", ["operator"])
    revoked_org, _, _ = await create_org_attestor(
        specializations=["healthcare"], jurisdictions=["US"], slug_prefix="alone"
    )
    attestation_id = await _attestation(requestor_id, "offered")
    await _offer(attestation_id, revoked_org, "offered")

    await _set_capability(revoked_org, "revoked")

    assert (await _load(attestation_id)).status == "needs_admin"
    assert [notice["target_id"] for notice in sent["admins"]] == [attestation_id]


@pytest.mark.parametrize("status", ["accepted", "in_review", "revision_requested"])
async def test_revocation_returns_undelivered_reviews_to_admins(
    status: str,
    sent: dict[str, list[dict[str, Any]]],
) -> None:
    """A review the org has not delivered is taken off it and queued for an admin.

    Clearing the org also locks the workspace: access follows the assigned org.
    """
    requestor_id = await create_user(f"revoke-{status}@auracles.space", ["operator"])
    revoked_org, reviewer_id, member_id = await create_org_attestor(
        specializations=["healthcare"], jurisdictions=["US"], slug_prefix="review"
    )
    attestation_id = await _attestation(requestor_id, status)
    await _assign(attestation_id, revoked_org, member_id)

    await _set_capability(revoked_org, "revoked")

    attestation = await _load(attestation_id)
    assert attestation.status == "needs_admin"
    assert attestation.attestor_org_id is None
    assert attestation.reviewing_member_id is None
    assert attestation.completion_due_at is None
    assert await _offers(attestation_id) == {(revoked_org, "superseded", 0)}
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attestation_reassigned",
                AuditLog.target_id == attestation_id,
            )
        )
    assert audit is not None
    assert audit.metadata_["reason"] == "attestor_capability_revoked"
    assert [notice["target_id"] for notice in sent["admins"]] == [attestation_id]
    reviewer_notices = [
        call
        for call in sent["users"]
        if call["notification_type"] == "attestation_reassigned"
        and call["user_id"] == str(reviewer_id)
    ]
    assert len(reviewer_notices) == 1


@pytest.mark.parametrize("status", ["report_submitted", "disputed"])
async def test_revocation_leaves_delivered_reviews_to_finish(
    status: str,
    sent: dict[str, list[dict[str, Any]]],
) -> None:
    """A delivered report stays with its org for the requestor or admin to settle."""
    requestor_id = await create_user(f"keep-{status}@auracles.space", ["operator"])
    revoked_org, _, member_id = await create_org_attestor(
        specializations=["healthcare"], jurisdictions=["US"], slug_prefix="keep"
    )
    attestation_id = await _attestation(requestor_id, status)
    await _assign(attestation_id, revoked_org, member_id)

    await _set_capability(revoked_org, "revoked")

    attestation = await _load(attestation_id)
    assert attestation.status == status
    assert attestation.attestor_org_id == revoked_org
    assert sent["admins"] == []


async def test_suspension_leaves_offers_and_reviews_untouched(
    sent: dict[str, list[dict[str, Any]]],
) -> None:
    """Suspension is temporary, so work stays where it is for reinstatement."""
    requestor_id = await create_user("suspend-requestor@auracles.space", ["operator"])
    org_id, _, member_id = await create_org_attestor(
        specializations=["healthcare"], jurisdictions=["US"], slug_prefix="susp"
    )
    await create_org_attestor(
        specializations=["healthcare"], jurisdictions=["US"], slug_prefix="other"
    )
    offered_id = await _attestation(requestor_id, "offered")
    await _offer(offered_id, org_id, "offered")
    review_id = await _attestation(requestor_id, "in_review")
    await _assign(review_id, org_id, member_id)

    await _set_capability(org_id, "suspended")

    assert await _offers(offered_id) == {(org_id, "offered", 0)}
    review = await _load(review_id)
    assert review.status == "in_review"
    assert review.attestor_org_id == org_id
    assert sent["admins"] == []
