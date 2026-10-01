"""Notifications for a person paid directly, rather than through an org.

An Organization heard when its payout was requested, completed or failed. A
person paid directly heard nothing: outcome notices were gated on
`payout.org_id is not None`, and the only individual notice that existed
covered a failed Stripe bank payout. On Paystack — the pilot's own rail — a
payout settles straight to the bank, can defer for hours on an underfunded
balance, or be abandoned on a held transfer, and the payee could not learn
which. QA found it by requesting a payout on an individual account.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from app.modules.financials import notifications


class RecordingDispatch:
    """Capture queued notifications instead of hitting Celery."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.sent: list[dict[str, Any]] = []

    def delay(self, **kwargs: Any) -> None:
        """Record one queued notification."""
        self.sent.append(kwargs)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> RecordingDispatch:
    """Swap the dispatcher for an in-memory recorder."""
    recording = RecordingDispatch()
    monkeypatch.setattr(notifications, "dispatch_project_notification", recording)
    return recording


def test_completed_payout_tells_the_payee_the_money_landed(
    recorder: RecordingDispatch,
) -> None:
    """A completed payout is the one event the payee cannot see for themselves."""
    payee_id = uuid4()
    payout_id = uuid4()

    notifications.notify_payout_completed(
        payee_id,
        payout_id=payout_id,
        amount=Decimal("85000.00"),
        currency="NGN",
    )

    assert len(recorder.sent) == 1
    sent = recorder.sent[0]
    assert sent["user_id"] == str(payee_id)
    assert sent["notification_type"] == "payout_completed"
    assert "₦85,000.00" in sent["body"]
    assert sent["link"] == "/dashboard/financials"
    # Keyed on the payout, so a webhook redelivery does not notify twice.
    assert str(payout_id) in sent["dedupe_key"]


def test_failed_payout_names_the_reason_when_the_provider_gave_one(
    recorder: RecordingDispatch,
) -> None:
    """A payee who is not told why cannot fix the thing that broke."""
    notifications.notify_payout_failed(
        uuid4(),
        payout_id=uuid4(),
        amount=Decimal("85000.00"),
        currency="NGN",
        failure_reason="Account name mismatch",
    )

    sent = recorder.sent[0]
    assert sent["notification_type"] == "payout_failed"
    assert "Account name mismatch" in sent["body"]


def test_failed_payout_still_reassures_when_no_reason_is_given(
    recorder: RecordingDispatch,
) -> None:
    """Paystack does not always supply a reason; silence is not an option.

    The payee still has to learn the money did not move and is not lost, so the
    notice must stand on its own without a provider message.
    """
    notifications.notify_payout_failed(
        uuid4(),
        payout_id=uuid4(),
        amount=Decimal("85000.00"),
        currency="NGN",
        failure_reason=None,
    )

    sent = recorder.sent[0]
    assert sent["notification_type"] == "payout_failed"
    assert sent["body"].strip()
    # No dangling "Reason:" with nothing after it.
    assert "Reason:" not in sent["body"]


def test_a_queue_failure_never_escapes_the_notifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broker outage must not roll back a payout that already settled.

    These are called after the webhook's transaction commits, so raising here
    would fail the webhook and invite the provider to redeliver a settlement
    that already happened.
    """

    class ExplodingDispatch:
        """Stand in for an unreachable broker."""

        def delay(self, **kwargs: Any) -> None:
            """Fail the way a dead broker does."""
            raise RuntimeError("broker unreachable")

    monkeypatch.setattr(
        notifications, "dispatch_project_notification", ExplodingDispatch()
    )

    notifications.notify_payout_completed(
        uuid4(),
        payout_id=uuid4(),
        amount=Decimal("1.00"),
        currency="NGN",
    )
