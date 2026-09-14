"""Recipients, labels, links and wording of the Slice C org money notifications.

Every helper here is called after the transaction that made the change has
committed; these tests pin what each one queues so a service change cannot
silently drop a recipient, double-notify an owner who is also the actor, or
point a link at the wrong page. Money is always shown with its own currency
(Naira is the primary rail), never an assumed dollar sign.

Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md
§Slice C.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

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


def _recipients(recorder: RecordingDispatch) -> list[str]:
    return [call["user_id"] for call in recorder.sent]


def test_format_money_uses_the_currency_symbol_not_an_assumed_dollar() -> None:
    """Naira renders with its own symbol and grouping; unknown codes stay explicit."""
    assert notifications.format_money(Decimal("50000"), "NGN") == "₦50,000.00"
    assert notifications.format_money(Decimal("12.5"), "usd") == "$12.50"
    assert notifications.format_money(Decimal("7"), "KES") == "KES 7.00"


def test_payout_requested_targets_owners_with_amount_and_financials_link(
    recorder: RecordingDispatch,
) -> None:
    """Owners hear the formatted amount and land on the financials tab."""
    org_id, payout_id = uuid4(), uuid4()
    owners = [uuid4(), uuid4()]

    notifications.notify_org_payout_requested(
        owners,
        org_id=org_id,
        org_name="Acme",
        payout_id=payout_id,
        amount=Decimal("75000.00"),
        currency="NGN",
    )

    assert _recipients(recorder) == [str(owner) for owner in owners]
    call = recorder.sent[0]
    assert call["notification_type"] == "org_payout_requested"
    assert "Acme" in call["title"]
    assert "₦75,000.00" in call["body"]
    assert call["link"] == f"/dashboard/organizations/{org_id}/financials"
    assert call["dedupe_key"].endswith(str(payout_id))


def test_payout_completed_reaches_owners_and_requester_once_each(
    recorder: RecordingDispatch,
) -> None:
    """A requester who is also an owner is not notified twice."""
    org_id, payout_id = uuid4(), uuid4()
    owner_a, owner_b = uuid4(), uuid4()

    notifications.notify_org_payout_completed(
        [owner_a, owner_b],
        requester_id=owner_a,
        org_id=org_id,
        org_name="Acme",
        payout_id=payout_id,
        amount=Decimal("1000"),
        currency="NGN",
    )

    assert _recipients(recorder) == [str(owner_a), str(owner_b)]
    call = recorder.sent[0]
    assert call["notification_type"] == "org_payout_completed"
    assert "₦1,000.00" in call["body"]
    assert call["link"] == f"/dashboard/organizations/{org_id}/financials"


def test_payout_completed_adds_a_non_owner_requester(
    recorder: RecordingDispatch,
) -> None:
    """A requester who has since stopped being an owner still hears the outcome."""
    owner, requester = uuid4(), uuid4()

    notifications.notify_org_payout_completed(
        [owner],
        requester_id=requester,
        org_id=uuid4(),
        org_name="Acme",
        payout_id=uuid4(),
        amount=Decimal("1000"),
        currency="NGN",
    )

    assert _recipients(recorder) == [str(owner), str(requester)]


def test_payout_failed_includes_reason_when_present(
    recorder: RecordingDispatch,
) -> None:
    """The failure body names the provider's reason so owners can act on it."""
    org_id = uuid4()
    owner = uuid4()

    notifications.notify_org_payout_failed(
        [owner],
        requester_id=None,
        org_id=org_id,
        org_name="Acme",
        payout_id=uuid4(),
        amount=Decimal("2500"),
        currency="NGN",
        failure_reason="The destination account is closed.",
    )

    assert _recipients(recorder) == [str(owner)]
    call = recorder.sent[0]
    assert call["notification_type"] == "org_payout_failed"
    assert "₦2,500.00" in call["body"]
    assert "The destination account is closed." in call["body"]
    assert call["link"] == f"/dashboard/organizations/{org_id}/financials"


def test_payout_failed_without_reason_reads_cleanly(
    recorder: RecordingDispatch,
) -> None:
    """No reason means no dangling "Reason:" clause."""
    notifications.notify_org_payout_failed(
        [uuid4()],
        requester_id=None,
        org_id=uuid4(),
        org_name="Acme",
        payout_id=uuid4(),
        amount=Decimal("2500"),
        currency="NGN",
        failure_reason=None,
    )

    assert "Reason" not in recorder.sent[0]["body"]


def test_purchase_completed_reaches_owners_and_initiator_with_library_link(
    recorder: RecordingDispatch,
) -> None:
    """The buyer and the owners land on the org library."""
    org_id, transaction_id = uuid4(), uuid4()
    owner, initiator = uuid4(), uuid4()

    notifications.notify_org_purchase_completed(
        [owner],
        initiator_id=initiator,
        org_id=org_id,
        org_name="Acme",
        transaction_id=transaction_id,
        framework_title="Revenue Playbook",
        amount=Decimal("249.00"),
        currency="NGN",
    )

    assert _recipients(recorder) == [str(owner), str(initiator)]
    call = recorder.sent[0]
    assert call["notification_type"] == "org_purchase_completed"
    assert "Revenue Playbook" in call["title"] + call["body"]
    assert "₦249.00" in call["body"]
    assert call["link"] == f"/dashboard/organizations/{org_id}/operator/library"
    assert call["dedupe_key"].endswith(str(transaction_id))


def test_purchase_failed_links_to_billing_and_carries_reason(
    recorder: RecordingDispatch,
) -> None:
    """A failed purchase points at billing, with the reason when one exists."""
    org_id = uuid4()
    owner = uuid4()

    notifications.notify_org_purchase_failed(
        [owner],
        initiator_id=owner,
        org_id=org_id,
        org_name="Acme",
        transaction_id=uuid4(),
        framework_title="Revenue Playbook",
        amount=Decimal("249.00"),
        currency="NGN",
        failure_reason="Insufficient funds.",
    )

    assert _recipients(recorder) == [str(owner)]
    call = recorder.sent[0]
    assert call["notification_type"] == "org_purchase_failed"
    assert "Insufficient funds." in call["body"]
    assert call["link"] == f"/dashboard/organizations/{org_id}/financials"


def test_invoice_ready_targets_owners_with_billing_link(
    recorder: RecordingDispatch,
) -> None:
    """Owners are told the purchase invoice exists and where to find it."""
    org_id = uuid4()
    owners = [uuid4()]

    notifications.notify_org_invoice_ready(
        owners,
        org_id=org_id,
        org_name="Acme",
        transaction_id=uuid4(),
        framework_title="Revenue Playbook",
    )

    call = recorder.sent[0]
    assert _recipients(recorder) == [str(owners[0])]
    assert call["notification_type"] == "org_invoice_ready"
    assert "Revenue Playbook" in call["body"]
    assert call["link"] == f"/dashboard/organizations/{org_id}/financials"


def test_license_granted_skips_the_actor(recorder: RecordingDispatch) -> None:
    """An admin granting a Framework to themself is not told about it."""
    org_id = uuid4()
    actor, grantee = uuid4(), uuid4()

    notifications.notify_org_license_granted(
        [actor, grantee],
        actor_id=actor,
        org_id=org_id,
        org_name="Acme",
        license_id=uuid4(),
        framework_title="Revenue Playbook",
    )

    assert _recipients(recorder) == [str(grantee)]
    call = recorder.sent[0]
    assert call["notification_type"] == "org_license_granted"
    assert "Revenue Playbook" in call["title"] + call["body"]
    assert call["link"] == f"/dashboard/organizations/{org_id}/operator/library"


def test_license_revoked_skips_the_actor(recorder: RecordingDispatch) -> None:
    """Revocation reaches the grantee but not the member who revoked it."""
    org_id = uuid4()
    actor, grantee = uuid4(), uuid4()

    notifications.notify_org_license_revoked(
        [grantee, actor],
        actor_id=actor,
        org_id=org_id,
        org_name="Acme",
        license_id=uuid4(),
        framework_title="Revenue Playbook",
    )

    assert _recipients(recorder) == [str(grantee)]
    call = recorder.sent[0]
    assert call["notification_type"] == "org_license_revoked"
    assert call["link"] == f"/dashboard/organizations/{org_id}/operator/library"


def test_framework_suspended_carries_admin_reason(recorder: RecordingDispatch) -> None:
    """Owners of the selling org hear which Framework was pulled and why."""
    org_id, framework_id = uuid4(), uuid4()
    owners = [uuid4(), uuid4()]

    notifications.notify_org_framework_suspended(
        owners,
        org_id=org_id,
        org_name="Acme",
        framework_id=framework_id,
        framework_title="Revenue Playbook",
        reason="Copyright complaint upheld.",
    )

    assert _recipients(recorder) == [str(owner) for owner in owners]
    call = recorder.sent[0]
    assert call["notification_type"] == "org_framework_suspended"
    assert "Revenue Playbook" in call["title"]
    assert "Copyright complaint upheld." in call["body"]
    assert call["link"] == (
        f"/dashboard/organizations/{org_id}/frameworks/{framework_id}"
    )


def test_framework_published_skips_the_publishing_owner(
    recorder: RecordingDispatch,
) -> None:
    """The owner who pressed publish is not told they published."""
    org_id, framework_id = uuid4(), uuid4()
    actor, other_owner = uuid4(), uuid4()

    notifications.notify_org_framework_published(
        [actor, other_owner],
        actor_id=actor,
        org_id=org_id,
        org_name="Acme",
        framework_id=framework_id,
        framework_title="Revenue Playbook",
    )

    assert _recipients(recorder) == [str(other_owner)]
    call = recorder.sent[0]
    assert call["notification_type"] == "org_framework_published"
    assert call["link"] == (
        f"/dashboard/organizations/{org_id}/frameworks/{framework_id}"
    )
