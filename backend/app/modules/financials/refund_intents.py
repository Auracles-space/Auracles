"""Crash-proof refund intents and their reconciliation.

Every provider refund call sits inside a database transaction that also
writes the local refund state. A crash after the provider accepts the refund
but before that transaction commits used to be invisible: money left the
platform, and no local row said so. The Paystack settlement sweeper cannot
see it either — it keys on the `refund_requested` ledger row, which rolled
back with everything else.

The fix is an intent written durably *before* the provider is called, on its
own committed session. The normal flow then stamps the same `intent_key`
onto the `refund_requested` event, closing the intent implicitly. An hourly
sweep picks up intents past a grace window with no matching outcome and asks
the provider directly whether a refund exists for that charge:

* a refund exists — CRITICAL: money moved with no local record. The intent
  is flagged (audit + ledger) and admins are paged to repair state through
  the existing refund tools.
* no refund exists — the attempt died before the provider acted; the intent
  is closed as abandoned.

Covers both rails: Stripe (whose refunds previously had no reconciliation at
all) and the pre-commit window Paystack's settlement sweeper cannot reach.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TypedDict
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.integrations import paystack, stripe
from app.integrations.paystack import PaystackProviderError, PaystackRefund
from app.integrations.stripe import StripeProviderError, StripeRefund
from app.modules.admin.notifications import notify_admins_review_pending
from app.modules.financials.ledger import record_financial_event
from app.modules.financials.models import FinancialEvent

INITIATED_EVENT = "refund_initiated"
FLAGGED_EVENT = "refund_intent_flagged"
CLOSED_EVENT = "refund_intent_closed"

# Long enough that every healthy refund flow commits its refund_requested row
# first; short enough that a crash-orphaned provider refund is surfaced the
# same hour it happened.
INTENT_GRACE = timedelta(minutes=30)


class RefundIntentSweepResult(TypedDict):
    """Counts from one refund-intent reconciliation run."""

    checked: int
    closed: int
    flagged: int
    unresolved: int


async def record_refund_intent(
    *,
    transaction_id: UUID,
    charge_ref: str,
    rail: str,
    amount: Decimal,
    currency: str,
    actor_id: UUID | None,
) -> str:
    """Durably record that a provider refund is about to be attempted.

    Committed on an independent session so the record survives whatever
    happens to the caller's transaction. Returns the intent key the caller
    must stamp onto its `refund_requested` event to close the intent.

    The actor rides in metadata rather than the `actor_id` foreign key on
    purpose: the caller's transaction typically holds the acting user's row
    FOR UPDATE (the 2FA check), and an FK insert from this second connection
    would wait on that lock while the caller awaits this write — a
    same-process deadlock.
    """
    intent_key = uuid4().hex
    async with async_session_factory() as db, db.begin():
        await record_financial_event(
            db,
            entity_type="transaction",
            entity_id=transaction_id,
            event_type=INITIATED_EVENT,
            amount=amount,
            currency=currency,
            provider=rail,
            provider_ref=charge_ref,
            metadata={
                "intent_key": intent_key,
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
    return intent_key


async def _intent_is_resolved(db: AsyncSession, intent_key: str) -> bool:
    """Report whether any outcome event already carries this intent key."""
    resolved = await db.scalar(
        select(FinancialEvent.id)
        .where(
            FinancialEvent.event_type.in_(
                ("refund_requested", FLAGGED_EVENT, CLOSED_EVENT)
            ),
            FinancialEvent.metadata_["intent_key"].astext == intent_key,
        )
        .limit(1)
    )
    return resolved is not None


async def _provider_refund_ids(intent: FinancialEvent) -> list[str] | None:
    """Ask the intent's rail which refunds exist for its charge.

    Returns None when the provider could not be asked, leaving the intent
    for the next run rather than guessing.
    """
    if intent.provider_ref is None:
        return []
    try:
        refunds: list[PaystackRefund] | list[StripeRefund]
        if intent.provider == "paystack":
            refunds = await paystack.list_refunds(
                transaction_reference=intent.provider_ref
            )
        else:
            refunds = await stripe.list_refunds(
                payment_intent_id=intent.provider_ref
            )
    except (StripeProviderError, PaystackProviderError) as exc:
        logger.bind(
            module="financials",
            action="reconcile_refund_intents",
            transaction_id=str(intent.entity_id),
        ).error("refund_intent_probe_failed", error=str(exc))
        return None
    return [refund.id for refund in refunds]


async def reconcile_refund_intents(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> RefundIntentSweepResult:
    """Resolve refund intents whose outcome never reached the database.

    Args:
        db: Async session already inside the caller's transaction.
        now: Clock override for tests.

    Returns:
        Counts of intents checked and how each was resolved.
    """
    moment = now or datetime.now(UTC)
    cutoff = moment - INTENT_GRACE
    intents = (
        (
            await db.execute(
                select(FinancialEvent)
                .where(
                    FinancialEvent.event_type == INITIATED_EVENT,
                    FinancialEvent.occurred_at < cutoff,
                )
                .order_by(FinancialEvent.occurred_at)
            )
        )
        .scalars()
        .all()
    )

    result: RefundIntentSweepResult = {
        "checked": 0,
        "closed": 0,
        "flagged": 0,
        "unresolved": 0,
    }
    for intent in intents:
        intent_key = intent.metadata_.get("intent_key")
        if not isinstance(intent_key, str):
            continue
        if await _intent_is_resolved(db, intent_key):
            continue
        result["checked"] += 1
        log = logger.bind(
            module="financials",
            action="reconcile_refund_intents",
            transaction_id=str(intent.entity_id),
        )

        refund_ids = await _provider_refund_ids(intent)
        if refund_ids is None:
            result["unresolved"] += 1
            continue

        if not refund_ids:
            # The attempt died before the provider acted; nothing moved.
            await record_financial_event(
                db,
                entity_type="transaction",
                entity_id=intent.entity_id,
                event_type=CLOSED_EVENT,
                provider=intent.provider,
                provider_ref=intent.provider_ref,
                reason_code="no_provider_refund_found",
                metadata={"intent_key": intent_key},
            )
            log.info("refund_intent_closed_abandoned")
            result["closed"] += 1
            continue

        # A refund exists at the provider with no local record: money left
        # the platform invisibly. CRITICAL, and an admin repairs state
        # through the existing refund tools.
        await record_financial_event(
            db,
            entity_type="transaction",
            entity_id=intent.entity_id,
            event_type=FLAGGED_EVENT,
            amount=intent.amount,
            currency=intent.currency,
            provider=intent.provider,
            provider_ref=intent.provider_ref,
            reason_code="untracked_provider_refund",
            metadata={
                "intent_key": intent_key,
                "provider_refund_ids": refund_ids,
            },
        )
        await write_audit(
            db=db,
            actor_id=None,
            action="untracked_refund_detected",
            target_type="transaction",
            target_id=intent.entity_id,
            metadata={
                "intent_key": intent_key,
                "provider_refund_ids": ",".join(refund_ids),
            },
        )
        log.critical("untracked_provider_refund_detected", refund_ids=refund_ids)
        notify_admins_review_pending(
            domain="refund",
            target_id=intent.entity_id,
            body=(
                "A provider refund exists for a transaction whose local "
                "refund record was lost mid-write. Verify at the provider "
                "and repair the transaction state."
            ),
            link=f"/admin/money/{intent.entity_id}",
        )
        result["flagged"] += 1
    return result
