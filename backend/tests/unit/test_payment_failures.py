"""Unit tests for provider-neutral payment failure normalization.

The ledger stores one failure vocabulary so a Nigerian Paystack decline and a
global Stripe decline are queryable the same way. These tests pin the mapping
from each provider's own error shape onto that vocabulary.
"""

from __future__ import annotations

from app.integrations.payment_failures import (
    CANONICAL_FAILURE_CODES,
    normalize_paystack_failure,
    normalize_stripe_failure,
)


def test_stripe_decline_code_outranks_generic_error_code() -> None:
    """Stripe's `decline_code` names the real cause; `code` is only a category.

    A `card_declined` with `decline_code: insufficient_funds` must not be
    flattened to `card_declined`, or every decline looks alike again.
    """
    failure = normalize_stripe_failure(
        {
            "last_payment_error": {
                "code": "card_declined",
                "decline_code": "insufficient_funds",
                "message": "Your card has insufficient funds.",
            }
        }
    )

    assert failure.code == "insufficient_funds"
    assert failure.message == "Your card has insufficient funds."
    assert failure.provider_code == "insufficient_funds"


def test_stripe_falls_back_to_error_code_when_no_decline_code() -> None:
    """An error without a decline code still maps to a canonical cause."""
    failure = normalize_stripe_failure(
        {
            "last_payment_error": {
                "code": "expired_card",
                "message": "Your card has expired.",
            }
        }
    )

    assert failure.code == "expired_card"
    assert failure.provider_code == "expired_card"


def test_stripe_reads_transfer_failure_fields() -> None:
    """Payout transfer failures carry `failure_code`, not `last_payment_error`.

    This is the path that currently stores only the last 4 of the transfer ref
    and discards the cause entirely.
    """
    failure = normalize_stripe_failure(
        {
            "failure_code": "account_closed",
            "failure_message": "The bank account has been closed.",
        }
    )

    assert failure.code == "account_invalid"
    assert failure.message == "The bank account has been closed."
    assert failure.provider_code == "account_closed"


def test_stripe_unknown_code_is_preserved_not_discarded() -> None:
    """An unmapped provider code still records the raw value for diagnosis."""
    failure = normalize_stripe_failure(
        {"last_payment_error": {"code": "some_new_stripe_code", "message": "Nope."}}
    )

    assert failure.code == "unknown"
    assert failure.provider_code == "some_new_stripe_code"
    assert failure.message == "Nope."


def test_stripe_empty_object_yields_unknown_without_raising() -> None:
    """A malformed provider payload must never break the webhook handler."""
    failure = normalize_stripe_failure({})

    assert failure.code == "unknown"
    assert failure.provider_code is None


def test_paystack_gateway_response_maps_to_canonical_code() -> None:
    """Paystack reports the cause as prose in `gateway_response`."""
    failure = normalize_paystack_failure(
        {
            "gateway_response": "Insufficient Funds",
            "message": "Transaction failed",
        }
    )

    assert failure.code == "insufficient_funds"
    assert failure.provider_code == "Insufficient Funds"


def test_paystack_transfer_reason_is_read() -> None:
    """Paystack transfer failures carry the cause in `reason`."""
    failure = normalize_paystack_failure(
        {"reason": "Account name mismatch", "status": "failed"}
    )

    assert failure.code == "account_invalid"
    assert failure.message == "Account name mismatch"


def test_paystack_abandoned_transaction_is_not_a_decline() -> None:
    """An abandoned checkout is a distinct outcome from a bank decline."""
    failure = normalize_paystack_failure({"gateway_response": "Abandoned"})

    assert failure.code == "payment_abandoned"


def test_paystack_empty_payload_yields_unknown() -> None:
    """A malformed Paystack payload must never break the webhook handler."""
    failure = normalize_paystack_failure({})

    assert failure.code == "unknown"


def test_every_mapped_code_is_declared_canonical() -> None:
    """Normalizers may only emit codes from the published vocabulary.

    Admin filters and dashboards are built against `CANONICAL_FAILURE_CODES`,
    so an undeclared code would be invisible in the UI.
    """
    emitted = {
        normalize_stripe_failure(
            {"last_payment_error": {"code": "card_declined", "decline_code": raw}}
        ).code
        for raw in ("insufficient_funds", "expired_card", "generic_decline")
    }
    emitted |= {
        normalize_paystack_failure({"gateway_response": raw}).code
        for raw in ("Insufficient Funds", "Declined", "Abandoned")
    }

    assert emitted <= CANONICAL_FAILURE_CODES
