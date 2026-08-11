"""Provider-neutral normalization of payment failure causes.

Stripe and Paystack report failures in unrelated shapes: Stripe nests a coded
error under `last_payment_error` (or `failure_code` on transfers), while
Paystack returns prose in `gateway_response` or `reason`. Storing either shape
raw would mean admin dashboards and failure filters had to special-case each
provider, and adding a provider would mean rewriting them.

These functions map both onto one canonical vocabulary written to
`financial_events.reason_code`, keeping the provider's own value in
`provider_code` so nothing is lost when a code is not yet mapped.

Maps to: FR-FIN-* payment traceability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# The published failure vocabulary. Admin filters are built against this set, so
# a normalizer must never emit a code that is not declared here.
CANONICAL_FAILURE_CODES = frozenset(
    {
        "insufficient_funds",
        "card_declined",
        "expired_card",
        "invalid_card_details",
        "authentication_required",
        "processing_error",
        "payment_abandoned",
        "account_invalid",
        "limit_exceeded",
        "unknown",
    }
)

# Stripe decline codes and error codes both map here. Decline codes are checked
# first because they name the cause, while the error code names only a category
# ("card_declined" tells an admin nothing a status column did not already say).
_STRIPE_CODE_MAP = {
    # decline_code values
    "insufficient_funds": "insufficient_funds",
    "expired_card": "expired_card",
    "incorrect_cvc": "invalid_card_details",
    "incorrect_number": "invalid_card_details",
    "invalid_expiry_month": "invalid_card_details",
    "invalid_expiry_year": "invalid_card_details",
    "card_not_supported": "card_declined",
    "currency_not_supported": "card_declined",
    "do_not_honor": "card_declined",
    "generic_decline": "card_declined",
    "lost_card": "card_declined",
    "stolen_card": "card_declined",
    "pickup_card": "card_declined",
    "transaction_not_allowed": "card_declined",
    "withdrawal_count_limit_exceeded": "limit_exceeded",
    "card_velocity_exceeded": "limit_exceeded",
    "amount_too_large": "limit_exceeded",
    # error code values
    "card_declined": "card_declined",
    "authentication_required": "authentication_required",
    "processing_error": "processing_error",
    "payment_intent_authentication_failure": "authentication_required",
    # transfer / payout failure codes
    "account_closed": "account_invalid",
    "no_account": "account_invalid",
    "invalid_account_number": "account_invalid",
    "account_frozen": "account_invalid",
    "bank_account_restricted": "account_invalid",
    "debit_not_authorized": "account_invalid",
    "insufficient_capabilities": "account_invalid",
    "could_not_process": "processing_error",
}

# Paystack reports prose, so matching is by substring on the lowercased value.
# Ordered: the first marker found wins, so put specific phrases before general
# ones ("insufficient" must beat "declined" when both could appear).
_PAYSTACK_MARKERS: tuple[tuple[str, str], ...] = (
    ("insufficient", "insufficient_funds"),
    ("expired", "expired_card"),
    ("abandoned", "payment_abandoned"),
    ("cancelled", "payment_abandoned"),
    ("canceled", "payment_abandoned"),
    ("timeout", "payment_abandoned"),
    ("timed out", "payment_abandoned"),
    ("incorrect pin", "invalid_card_details"),
    ("invalid pin", "invalid_card_details"),
    ("invalid cvv", "invalid_card_details"),
    ("invalid card", "invalid_card_details"),
    ("account name", "account_invalid"),
    ("account number", "account_invalid"),
    ("invalid account", "account_invalid"),
    ("account not found", "account_invalid"),
    ("mismatch", "account_invalid"),
    ("limit", "limit_exceeded"),
    ("exceed", "limit_exceeded"),
    ("otp", "authentication_required"),
    ("authentication", "authentication_required"),
    ("declined", "card_declined"),
    ("do not honor", "card_declined"),
    ("failed", "processing_error"),
    ("error", "processing_error"),
)


@dataclass(frozen=True)
class PaymentFailure:
    """A payment failure expressed in provider-neutral terms.

    Attributes:
        code: Canonical cause from `CANONICAL_FAILURE_CODES`.
        message: Provider's human-readable message, if one was supplied.
        provider_code: The provider's own raw code or phrase, preserved so an
            unmapped cause is still diagnosable.
    """

    code: str
    message: str | None
    provider_code: str | None


def _clean_str(value: Any) -> str | None:
    """Return a non-empty trimmed string, or None for anything else."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def normalize_stripe_failure(event_object: dict[str, Any]) -> PaymentFailure:
    """Map a Stripe object's failure fields onto the canonical vocabulary.

    Reads `last_payment_error` (payment intents) and the flat
    `failure_code`/`failure_message` pair (transfers and payouts). A malformed
    or absent payload yields `unknown` rather than raising, because a webhook
    handler must not fail on an unexpected provider shape.

    Args:
        event_object: The Stripe event's `data.object` mapping.

    Returns:
        The normalized failure. `code` is `unknown` when nothing maps.
    """
    error = event_object.get("last_payment_error")
    error = error if isinstance(error, dict) else {}

    # decline_code names the cause; code names only the category.
    raw_code = (
        _clean_str(error.get("decline_code"))
        or _clean_str(error.get("code"))
        or _clean_str(event_object.get("failure_code"))
    )
    message = _clean_str(error.get("message")) or _clean_str(
        event_object.get("failure_message")
    )

    if raw_code is None:
        outcome = event_object.get("outcome")
        if isinstance(outcome, dict):
            raw_code = _clean_str(outcome.get("reason"))
            message = message or _clean_str(outcome.get("seller_message"))

    code = _STRIPE_CODE_MAP.get(raw_code or "", "unknown")
    return PaymentFailure(code=code, message=message, provider_code=raw_code)


def normalize_paystack_failure(event_data: dict[str, Any]) -> PaymentFailure:
    """Map a Paystack payload's failure prose onto the canonical vocabulary.

    Paystack does not publish stable failure codes, so the cause arrives as
    `gateway_response` (charges) or `reason` (transfers). Matching is by
    substring against `_PAYSTACK_MARKERS` in declared order.

    Args:
        event_data: The Paystack event's `data` mapping.

    Returns:
        The normalized failure. `code` is `unknown` when nothing maps.
    """
    raw = _clean_str(event_data.get("gateway_response")) or _clean_str(
        event_data.get("reason")
    )
    message = _clean_str(event_data.get("message")) or raw

    if raw is None:
        return PaymentFailure(code="unknown", message=message, provider_code=None)

    lowered = raw.lower()
    for marker, canonical in _PAYSTACK_MARKERS:
        if marker in lowered:
            return PaymentFailure(code=canonical, message=message, provider_code=raw)

    return PaymentFailure(code="unknown", message=message, provider_code=raw)
