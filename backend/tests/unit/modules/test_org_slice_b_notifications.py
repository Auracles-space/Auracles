"""Recipients, labels, links and wording of the Slice B org notifications.

Every helper here is called after the transaction that made the change has
committed; these tests pin what each one queues so a service change cannot
silently drop a recipient or point a link at the wrong page.

Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md
§Slice B.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.organizations import notifications


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


def _only(recorder: RecordingDispatch) -> dict[str, Any]:
    """Return the single recorded dispatch."""
    assert len(recorder.sent) == 1, recorder.sent
    return recorder.sent[0]


def _recipients(recorder: RecordingDispatch) -> list[str]:
    return [call["user_id"] for call in recorder.sent]


def test_org_created_targets_creator_and_links_to_the_org(
    recorder: RecordingDispatch,
) -> None:
    """The creator gets one ``org_created`` pointing at the new dashboard."""
    user_id, org_id = uuid4(), uuid4()

    notifications.notify_org_created(user_id, org_id=org_id, org_name="Acme")

    call = _only(recorder)
    assert call["user_id"] == str(user_id)
    assert call["notification_type"] == "org_created"
    assert "Acme" in call["title"] + call["body"]
    assert call["link"] == f"/dashboard/organizations/{org_id}"


def test_profile_updated_names_fields_but_never_values(
    recorder: RecordingDispatch,
) -> None:
    """Other owners hear which fields changed; the new values stay out."""
    org_id = uuid4()
    owners: list[UUID] = [uuid4(), uuid4()]

    notifications.notify_org_profile_updated(
        owners,
        org_id=org_id,
        org_name="Acme",
        actor_name="Ada",
        changed_fields=["name", "website"],
    )

    assert _recipients(recorder) == [str(owner) for owner in owners]
    body = recorder.sent[0]["body"]
    assert "Ada" in body and "name" in body and "website" in body
    assert recorder.sent[0]["notification_type"] == "org_profile_updated"
    assert recorder.sent[0]["link"] == f"/dashboard/organizations/{org_id}"


def test_deactivated_reaches_every_member_with_closure_copy(
    recorder: RecordingDispatch,
) -> None:
    """Members learn the org is closed and hidden, data kept, and who to ask."""
    org_id = uuid4()
    members: list[UUID] = [uuid4(), uuid4(), uuid4()]

    notifications.notify_org_deactivated(
        members,
        org_id=org_id,
        org_name="Acme",
        closed_by_name="Ada",
        reason="Winding down.",
    )

    assert _recipients(recorder) == [str(member) for member in members]
    call = recorder.sent[0]
    assert call["notification_type"] == "org_deactivated"
    body = call["body"].lower()
    assert "closed" in body and "hidden" in body and "retained" in body
    assert "ada" in body and "winding down." in body
    assert call["link"] == "/dashboard/organizations"


def test_deactivated_without_reason_still_reads_cleanly(
    recorder: RecordingDispatch,
) -> None:
    """No reason given means no dangling 'Reason:' fragment."""
    notifications.notify_org_deactivated(
        [uuid4()], org_id=uuid4(), org_name="Acme", closed_by_name="Ada", reason=None
    )

    assert "reason" not in _only(recorder)["body"].lower()


def test_reactivated_targets_owners(recorder: RecordingDispatch) -> None:
    """Owners hear the org is open again and land on its dashboard."""
    org_id = uuid4()
    owners: list[UUID] = [uuid4()]

    notifications.notify_org_reactivated(owners, org_id=org_id, org_name="Acme")

    call = _only(recorder)
    assert call["notification_type"] == "org_reactivated"
    assert call["link"] == f"/dashboard/organizations/{org_id}"


def test_kyb_submitted_acknowledges_submitter(recorder: RecordingDispatch) -> None:
    """The submitter is told the details are in review and will hear back."""
    user_id, org_id = uuid4(), uuid4()

    notifications.notify_org_kyb_submitted(user_id, org_id=org_id, org_name="Acme")

    call = _only(recorder)
    assert call["user_id"] == str(user_id)
    assert call["notification_type"] == "org_kyb_submitted"
    assert "in review" in call["body"].lower()
    assert "notify you" in call["body"].lower()
    assert call["link"] == f"/dashboard/organizations/{org_id}/verification"


def test_invitation_revoked_targets_invitee(recorder: RecordingDispatch) -> None:
    """The invitee is told the invitation was withdrawn."""
    user_id, org_id = uuid4(), uuid4()

    notifications.notify_invitation_revoked(user_id, org_id=org_id, org_name="Acme")

    call = _only(recorder)
    assert call["user_id"] == str(user_id)
    assert call["notification_type"] == "org_invitation_revoked"
    assert "Acme" in call["title"] + call["body"]
    assert call["link"] == "/settings/organizations"


def test_invitation_expired_targets_invitee(recorder: RecordingDispatch) -> None:
    """The invitee is told the invitation lapsed and can ask for a new one."""
    user_id, org_id = uuid4(), uuid4()

    notifications.notify_invitation_expired(user_id, org_id=org_id, org_name="Acme")

    call = _only(recorder)
    assert call["user_id"] == str(user_id)
    assert call["notification_type"] == "org_invitation_expired"
    assert "expired" in call["body"].lower()
    assert call["link"] == "/settings/organizations"


def test_every_helper_carries_the_org_id_payload(
    recorder: RecordingDispatch,
) -> None:
    """Each dispatch tags the org so the inbox can group by organization."""
    org_id = uuid4()
    notifications.notify_org_created(uuid4(), org_id=org_id, org_name="Acme")
    notifications.notify_org_reactivated([uuid4()], org_id=org_id, org_name="Acme")
    notifications.notify_invitation_expired(uuid4(), org_id=org_id, org_name="Acme")

    assert all(call["payload"]["org_id"] == str(org_id) for call in recorder.sent)
