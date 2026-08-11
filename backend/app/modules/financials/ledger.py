"""Append-only financial event ledger.

Records one row per money state change so a payment can be reconstructed in
order after the fact. `transactions.status` and `payouts.status` are overwritten
in place, and `audit_logs` is actor-centric with money events spread across
several `target_type` values — neither can answer "what happened to this
payment, and why did it fail".

Provider adapters normalize their own error shapes into `reason_code` before
calling in, so Stripe and Paystack failures share one queryable vocabulary.

Maps to: FR-FIN-* payment traceability.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.financials.models import FinancialEvent

# Mirrors ck_financial_events_entity_type. Kept here so a typo in a money path
# fails in the service with a clear error rather than as a constraint violation
# that rolls back the payment it was meant to describe.
ENTITY_TYPES = frozenset(
    {
        "transaction",
        "escrow",
        "payout",
        "partner_commission",
        "partner_payout",
    }
)

# Substrings that mark a metadata key as carrying a secret or cardholder data.
# The ledger is durable storage, so CLAUDE.md's "never log secrets" rule binds
# harder here than on a log line that ages out of a drain.
_SENSITIVE_KEY_MARKERS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "signature",
    "card",
    "cvv",
    "pan",
    "account_number",
    "bearer",
)


class FinancialLedgerError(ValueError):
    """Raised when a ledger write is malformed and must not persist."""


def _is_sensitive(key: str) -> bool:
    """Report whether a metadata key looks like it carries a secret."""
    lowered = key.lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def _sanitize_metadata(
    metadata: dict[str, Any] | None,
    *,
    event_type: str,
) -> dict[str, Any]:
    """Drop sensitive keys from ledger metadata, logging what was removed.

    Stripping rather than raising is deliberate: a money webhook must not fail
    because a caller passed an extra field, but the omission is logged so the
    offending call site is findable.

    Args:
        metadata: Caller-supplied metadata, possibly None.
        event_type: Event name, used only for the warning's context.

    Returns:
        A new dict containing only the safe keys.
    """
    if not metadata:
        return {}

    safe = {key: value for key, value in metadata.items() if not _is_sensitive(key)}
    dropped = sorted(set(metadata) - set(safe))
    if dropped:
        logger.bind(
            module="financials",
            action="record_financial_event",
            event_type=event_type,
        ).warning("ledger_metadata_keys_stripped", dropped_keys=",".join(dropped))
    return safe


async def record_financial_event(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: UUID,
    event_type: str,
    from_status: str | None = None,
    to_status: str | None = None,
    amount: Decimal | None = None,
    currency: str | None = None,
    provider: str | None = None,
    provider_ref: str | None = None,
    reason_code: str | None = None,
    reason_message: str | None = None,
    actor_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> FinancialEvent:
    """Append one money state change to the ledger without committing.

    The caller owns the transaction, so the event commits atomically with the
    state change it describes. A ledger row that outlived a rolled-back payment
    would assert money moved when it did not.

    Args:
        db: Async session already inside the caller's transaction.
        entity_type: Money object kind; one of `ENTITY_TYPES`.
        entity_id: Identifier of the transaction, escrow, or payout.
        event_type: snake_case event name, e.g. `purchase_failed`.
        from_status: Status before the change, None for creation events.
        to_status: Status after the change, None for non-transition events.
        amount: Money moved, if any. Requires `currency`.
        currency: ISO 4217 code. Requires `amount`.
        provider: `stripe` or `paystack`, when provider-driven.
        provider_ref: Provider's charge, transfer, or reference id.
        reason_code: Normalized failure cause, provider-neutral.
        reason_message: Provider's human-readable message.
        actor_id: User who caused the change; None for provider or task events.
        metadata: Extra context. Sensitive keys are stripped before storage.

    Returns:
        The flushed FinancialEvent, with its database-assigned id populated.

    Raises:
        FinancialLedgerError: If `entity_type` is unknown, or `amount` and
            `currency` are not both present or both absent.
    """
    if entity_type not in ENTITY_TYPES:
        raise FinancialLedgerError(
            f"Unknown financial entity type: {entity_type!r}. "
            f"Expected one of {sorted(ENTITY_TYPES)}."
        )
    if (amount is None) != (currency is None):
        raise FinancialLedgerError(
            "Ledger events must carry amount and currency together."
        )

    event = FinancialEvent(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        amount=amount,
        currency=currency.upper() if currency else None,
        provider=provider,
        provider_ref=provider_ref,
        reason_code=reason_code,
        reason_message=reason_message,
        actor_id=actor_id,
        metadata_=_sanitize_metadata(metadata, event_type=event_type),
    )
    db.add(event)
    await db.flush()

    # Every money movement reaches the log stream as well as the ledger, so an
    # operator watching logs sees the same events an admin queries later.
    logger.bind(
        module="financials",
        action=event_type,
        entity_type=entity_type,
        entity_id=str(entity_id),
    ).info(
        "financial_event_recorded",
        from_status=from_status,
        to_status=to_status,
        reason_code=reason_code,
    )
    return event
