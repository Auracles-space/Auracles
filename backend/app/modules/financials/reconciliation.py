"""Reconciliation for refunds whose settlement webhook never arrived.

Paystack accepts a refund immediately and reports its outcome later by
webhook. If that delivery is lost — our API down through their retries, a
misconfigured URL, an event dropped on their side — the purchase stays marked
refunded forever. When the refund actually succeeded that end state is
correct, but when it failed the buyer has paid, holds nothing, and never gets
their money back, and no other code path will ever notice.

This asks Paystack directly for any refund still unresolved past the
settlement window, and applies the real outcome through the same functions the
webhook uses.

Maps to: FR-FIN-* (Nigerian corridor refunds).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TypedDict
from uuid import UUID

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import paystack
from app.integrations.paystack import PaystackProviderError
from app.modules.financials.models import FinancialEvent, Transaction
from app.modules.financials.refunds import (
    REVERSED_EVENT,
    SETTLED_EVENT,
    reverse_refund,
    settle_refund,
)

# How long a refund may sit unsettled before we stop waiting for the webhook
# and ask Paystack ourselves. Long enough that a normal settlement, and
# Paystack's own webhook retries, complete well inside it — chasing sooner
# spends a provider call on refunds that were always going to arrive.
SETTLEMENT_GRACE = timedelta(hours=72)

# Provider statuses that resolve a refund. Anything else — `pending`,
# `processing`, or a status Paystack adds later — means the refund is still in
# flight and is left for the next run rather than guessed at.
_SETTLED_STATUSES = frozenset({"processed", "success", "successful"})
_FAILED_STATUSES = frozenset({"failed"})

_SOURCE = "reconciliation"


class ReconciliationResult(TypedDict):
    """Counts from one reconciliation run."""

    checked: int
    settled: int
    reversed: int
    unresolved: int


async def reconcile_pending_refunds(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> ReconciliationResult:
    """Resolve refunds left in flight past the settlement window.

    Only Paystack refunds are considered: Stripe returns a terminal status at
    creation, so a Stripe refund is never waiting on anything.

    A lookup that fails, or a refund Paystack still calls pending, leaves the
    row untouched for the next run. Treating either as a failed refund would
    restore access to a buyer who has already been paid back.

    Args:
        db: Async session already inside the caller's transaction.
        now: Clock override for tests.

    Returns:
        Counts of refunds checked and how each was resolved.
    """
    moment = now or datetime.now(UTC)
    cutoff = moment - SETTLEMENT_GRACE

    settled_subquery = (
        select(FinancialEvent.entity_id)
        .where(FinancialEvent.event_type.in_((SETTLED_EVENT, REVERSED_EVENT)))
        .scalar_subquery()
    )
    pending = list(
        (
            await db.execute(
                select(FinancialEvent)
                .where(
                    FinancialEvent.event_type == "refund_requested",
                    FinancialEvent.provider == "paystack",
                    FinancialEvent.occurred_at < cutoff,
                    FinancialEvent.entity_id.not_in(settled_subquery),
                )
                .order_by(FinancialEvent.occurred_at)
            )
        )
        .scalars()
        .all()
    )

    result: ReconciliationResult = {
        "checked": 0,
        "settled": 0,
        "reversed": 0,
        "unresolved": 0,
    }
    for event in pending:
        result["checked"] += 1
        outcome = await _resolve_one(db, event)
        result[outcome] += 1  # type: ignore[literal-required]
    if result["checked"]:
        logger.bind(module="financials", action="reconcile_pending_refunds").info(
            "refund_reconciliation_completed", **result
        )
    return result


async def _resolve_one(db: AsyncSession, event: FinancialEvent) -> str:
    """Ask Paystack about one refund and apply whatever it reports."""
    log = logger.bind(
        module="financials",
        action="reconcile_pending_refunds",
        transaction_id=event.entity_id,
    )
    if not event.provider_ref:
        # Predates the ledger row carrying the refund id, so there is nothing
        # to ask Paystack about. Surfaced for a human rather than guessed at.
        log.critical("refund_unreconcilable_without_provider_id")
        return "unresolved"

    try:
        refund = await paystack.fetch_refund(refund_id=event.provider_ref)
    except PaystackProviderError as exc:
        log.error("refund_status_lookup_failed", error=str(exc))
        return "unresolved"

    transaction = await _locked_transaction(db, event.entity_id)
    if transaction is None or transaction.status != "refunded":
        # Resolved by the webhook between the query and now.
        return "unresolved"

    status = (refund.status or "").lower()
    if status in _SETTLED_STATUSES:
        await settle_refund(db, transaction, source=_SOURCE)
        log.warning("refund_settled_without_webhook", provider_status=status)
        return "settled"
    if status in _FAILED_STATUSES:
        await reverse_refund(db, transaction, source=_SOURCE)
        log.critical("refund_reversed_without_webhook", provider_status=status)
        return "reversed"

    log.warning("refund_still_pending_at_provider", provider_status=status)
    return "unresolved"


async def _locked_transaction(
    db: AsyncSession,
    transaction_id: UUID,
) -> Transaction | None:
    """Load a transaction for update, so two runs cannot resolve it twice."""
    transaction: Transaction | None = await db.scalar(
        select(Transaction).where(Transaction.id == transaction_id).with_for_update()
    )
    return transaction
