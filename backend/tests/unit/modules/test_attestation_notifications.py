"""Recipients and links of attestation notifications.

Slice 3 of the organizations + attestation rework: the requestor must hear
about every outcome, and attestor-side notifications must land on the org
workspace rather than the requestor's detail page.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.attestation import notifications
from app.modules.attestation.models import Attestation, AttestationOffer


class RecordingDispatch:
    """Capture queued notifications instead of hitting Celery."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def delay(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> RecordingDispatch:
    """Swap the dispatcher for an in-memory recorder."""
    recording = RecordingDispatch()
    monkeypatch.setattr(notifications, "dispatch_project_notification", recording)
    return recording


def _attestation(
    *, org_id: UUID | None = None, status: str = "in_review"
) -> Attestation:
    """Build an unsaved attestation with ids set for link building."""
    return Attestation(
        id=uuid4(),
        target_type="framework",
        target_id=uuid4(),
        requestor_id=uuid4(),
        attestor_org_id=org_id,
        status=status,
        requested_specializations=[],
        requested_jurisdictions=[],
        fee_amount=Decimal("100.00"),
        currency="USD",
    )


def _by_user(recorder: RecordingDispatch, user_id: UUID) -> dict[str, Any]:
    return next(call for call in recorder.sent if call["user_id"] == str(user_id))


def test_released_reaches_requestor_reviewer_and_owners_with_their_own_links(
    recorder: RecordingDispatch,
) -> None:
    """Release tells the requestor (detail page) and the org side (workspace)."""
    org_id = uuid4()
    attestation = _attestation(org_id=org_id, status="released")
    reviewer_id = uuid4()
    owner_id = uuid4()

    notifications.notify_released(
        attestation,
        reason="requestor_accept_report",
        recipient_id=reviewer_id,
        owner_ids=[owner_id, reviewer_id],
    )

    assert {call["user_id"] for call in recorder.sent} == {
        str(attestation.requestor_id),
        str(reviewer_id),
        str(owner_id),
    }
    requestor_call = _by_user(recorder, attestation.requestor_id)
    assert requestor_call["link"] == f"/attestations/{attestation.id}"
    assert "complete" in requestor_call["body"].lower()
    workspace = f"/dashboard/organizations/{org_id}/attestations/{attestation.id}"
    assert _by_user(recorder, reviewer_id)["link"] == workspace
    assert _by_user(recorder, owner_id)["link"] == workspace


def test_offer_received_links_to_the_org_offers_tab(
    recorder: RecordingDispatch,
) -> None:
    """A new offer sends the org manager to their offers tab, not the requestor page."""
    attestation = _attestation(status="offered")
    org_id = uuid4()
    offer = AttestationOffer(
        id=uuid4(),
        attestation_id=attestation.id,
        org_id=org_id,
        cohort_index=0,
        status="offered",
        offered_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
    )
    recipient = uuid4()

    notifications.notify_org_offer_received(
        attestation, offer=offer, recipient_id=recipient
    )

    assert recorder.sent[0]["link"] == f"/dashboard/organizations/{org_id}/offers"


def test_attestor_side_events_link_to_the_workspace(
    recorder: RecordingDispatch,
) -> None:
    """Assignment, answered clarifications and disputes open the workspace."""
    org_id = uuid4()
    attestation = _attestation(org_id=org_id)
    reviewer_id = uuid4()
    workspace = f"/dashboard/organizations/{org_id}/attestations/{attestation.id}"

    notifications.notify_reviewer_assigned(attestation, reviewer_user_id=reviewer_id)
    notifications.notify_clarification_answered(
        attestation, attestor_id=reviewer_id, clarification_id=uuid4()
    )
    notifications.notify_dispute_raised(attestation, recipient_id=reviewer_id)

    reviewer_calls = [c for c in recorder.sent if c["user_id"] == str(reviewer_id)]
    assert len(reviewer_calls) == 3
    assert {c["link"] for c in reviewer_calls} == {workspace}


def test_dispute_raised_acknowledges_the_requestor(recorder: RecordingDispatch) -> None:
    """The requestor who disputed gets a receipt with the review timeline."""
    attestation = _attestation(org_id=uuid4(), status="disputed")

    notifications.notify_dispute_raised(attestation, recipient_id=uuid4())

    requestor_call = _by_user(recorder, attestation.requestor_id)
    assert requestor_call["notification_type"] == "attestation_disputed"
    assert requestor_call["link"] == f"/attestations/{attestation.id}"


def test_upheld_revise_tells_the_reviewer_to_revise_by_the_new_deadline(
    recorder: RecordingDispatch,
) -> None:
    """A revise outcome names the action and the due date, not a generic verdict."""
    org_id = uuid4()
    attestation = _attestation(org_id=org_id, status="revision_requested")
    attestation.completion_due_at = datetime(2026, 10, 2, 12, tzinfo=UTC)
    reviewer_id = uuid4()

    notifications.notify_dispute_resolved(
        attestation, outcome="upheld_revise", recipient_id=reviewer_id
    )

    reviewer_call = _by_user(recorder, reviewer_id)
    assert "revis" in reviewer_call["body"].lower()
    assert "2 Oct 2026" in reviewer_call["body"]
    assert (
        reviewer_call["link"]
        == f"/dashboard/organizations/{org_id}/attestations/{attestation.id}"
    )
    requestor_call = _by_user(recorder, attestation.requestor_id)
    assert "revis" in requestor_call["body"].lower()


def test_offer_expiry_tells_the_requestor_matching_continues(
    recorder: RecordingDispatch,
) -> None:
    """When a cohort lapses the requestor learns the search is still on."""
    attestation = _attestation(status="matching")

    notifications.notify_offer_expired_for_requestor(attestation)

    call = _by_user(recorder, attestation.requestor_id)
    assert call["notification_type"] == "attestation_offer_expired"
    assert call["link"] == f"/attestations/{attestation.id}"


def test_clarification_expiry_tells_the_requestor(recorder: RecordingDispatch) -> None:
    """A lapsed question is reported to the person who failed to answer it."""
    attestation = _attestation(org_id=uuid4())
    clarification_id = uuid4()

    notifications.notify_clarification_expired(
        attestation, clarification_id=clarification_id
    )

    call = _by_user(recorder, attestation.requestor_id)
    assert call["notification_type"] == "attestation_clarification_expired"
    assert call["payload"]["clarification_id"] == str(clarification_id)


def test_withdrawn_tells_each_org_holding_an_open_offer(
    recorder: RecordingDispatch,
) -> None:
    """Orgs with a live offer learn the request is gone, on their offers tab."""
    attestation = _attestation(status="cancelled")
    org_id = uuid4()
    recipient = uuid4()

    notifications.notify_withdrawn(attestation, org_id=org_id, recipient_id=recipient)

    call = _by_user(recorder, recipient)
    assert call["notification_type"] == "attestation_withdrawn"
    assert call["link"] == f"/dashboard/organizations/{org_id}/offers"
