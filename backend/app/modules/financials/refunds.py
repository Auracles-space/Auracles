"""Refund settlement outcomes, shared by the webhook and the sweeper.

A Paystack refund is accepted before the money moves, so its outcome arrives
later — normally as a `refund.processed` or `refund.failed` webhook, and
otherwise from the reconciliation task that asks Paystack directly when no
webhook ever came.

Both routes must produce the same result. The two functions here are that
single implementation: whoever learns the outcome first applies it, and the
other finds the refund already closed and does nothing.

Maps to: FR-FIN-* (Nigerian corridor refunds).
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.developer.models import PartnerCommission
from app.modules.financials.ledger import record_financial_event
from app.modules.financials.models import Escrow, Transaction
from app.modules.frameworks.models import License

SETTLED_EVENT = "refund_settled"
REVERSED_EVENT = "refund_failed"


async def settle_refund(
    db: AsyncSession,
    transaction: Transaction,
    *,
    source: str,
) -> None:
    """Close out a refund the provider confirmed it paid.

    No state moves. The purchase was marked refunded and its licences revoked
    when the refund was accepted, so this only records that the money actually
    reached the buyer — and marks the refund resolved, so reconciliation stops
    asking about it.

    Args:
        db: Async session already inside the caller's transaction.
        transaction: The refunded purchase.
        source: What learned the outcome — `webhook` or `reconciliation`.
    """
    await record_financial_event(
        db,
        entity_type="transaction",
        entity_id=transaction.id,
        event_type=SETTLED_EVENT,
        from_status="refunded",
        to_status="refunded",
        amount=transaction.amount,
        currency=transaction.currency,
        provider=transaction.provider,
        provider_ref=transaction.provider_ref,
        metadata={"source": source},
    )
    await write_audit(
        db=db,
        actor_id=transaction.payer_id,
        action="refund_settled",
        target_type="transaction",
        target_id=transaction.id,
        metadata={"provider": transaction.provider, "source": source},
    )
    logger.bind(
        module="financials",
        action="settle_refund",
        transaction_id=transaction.id,
    ).info("refund_settled", source=source)


async def reverse_refund(
    db: AsyncSession,
    transaction: Transaction,
    *,
    source: str,
) -> None:
    """Undo an optimistically applied refund the provider declined.

    Access is revoked as soon as Paystack accepts a refund, before the money
    has moved. When it declines, the buyer has paid and holds nothing, so the
    purchase and every licence it minted are restored to where they were.

    Any Partner commission the clearing task voided on seeing the purchase
    marked refunded is returned to `pending`, because the commission follows
    the sale: the refund never happened, so the Partner is owed for it exactly
    as before. It is not cleared here — whether the 48-hour window has elapsed
    is the clearing task's decision, and `pending` is the state it expects.

    For an escrow funding transaction (milestone or attestation fee) the same
    logic restores the hold instead: the escrow returns to `held` and the
    funding transaction to `completed`, so an admin can re-issue the refund.
    A child `refund` row from an escrow split is simply marked `failed` — the
    split's release portion already stands, so nothing else may move.

    Args:
        db: Async session already inside the caller's transaction.
        transaction: The transaction whose refund was declined.
        source: What learned the outcome — `webhook` or `reconciliation`.
    """
    licenses: list[License] = []
    if transaction.transaction_type == "refund":
        # A split's refund portion. The money never left the platform; the
        # funding transaction and released escrow stay exactly as they are.
        transaction.status = "failed"
        to_status = "failed"
    elif transaction.transaction_type in ("milestone", "attestation_fee"):
        escrows = list(
            (
                await db.execute(
                    select(Escrow)
                    .where(
                        Escrow.transaction_id == transaction.id,
                        Escrow.status == "refunded",
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        if escrows:
            # Full escrow refund declined: put the money back under hold so
            # an admin can re-issue the refund.
            for escrow in escrows:
                escrow.status = "held"
                escrow.refunded_at = None
                await write_audit(
                    db=db,
                    actor_id=None,
                    action="escrow_refund_reversed",
                    target_type="escrow",
                    target_id=escrow.id,
                    metadata={
                        "transaction_id": str(transaction.id),
                        "source": source,
                    },
                )
            transaction.status = "completed"
            to_status = "completed"
        else:
            # Split: the escrow is released, so the funding transaction must
            # stay refunded — flipping it back would double-count the money
            # already credited by the release child row. Fail the split's
            # child refund rows instead.
            to_status = "refunded"
            child_rows = list(
                (
                    await db.execute(
                        select(Transaction)
                        .where(
                            Transaction.transaction_type == "refund",
                            Transaction.ref_id == transaction.ref_id,
                            Transaction.ref_type == transaction.ref_type,
                            Transaction.status == "refunded",
                        )
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            for child in child_rows:
                child.status = "failed"
    else:
        transaction.status = "completed"
        to_status = "completed"
        licenses = list(
            (
                await db.execute(
                    select(License)
                    .where(
                        License.transaction_id == transaction.id,
                        License.status == "revoked",
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for license_row in licenses:
            license_row.status = "active"

        await _reinstate_voided_commissions(db, transaction)

    await record_financial_event(
        db,
        entity_type="transaction",
        entity_id=transaction.id,
        event_type=REVERSED_EVENT,
        from_status="refunded",
        to_status=to_status,
        amount=transaction.amount,
        currency=transaction.currency,
        provider=transaction.provider,
        provider_ref=transaction.provider_ref,
        reason_code="provider_declined_refund",
        metadata={"source": source},
    )
    await write_audit(
        db=db,
        actor_id=transaction.payer_id,
        action="refund_failed",
        target_type="transaction",
        target_id=transaction.id,
        metadata={
            "provider": transaction.provider,
            "source": source,
            "restored_license_ids": [str(row.id) for row in licenses],
        },
    )
    # CRITICAL, not ERROR: the ledger said refunded while the money never
    # moved, and a Contributor payout may have been sized against that.
    logger.bind(
        module="financials",
        action="reverse_refund",
        transaction_id=transaction.id,
    ).critical("refund_reversed_after_provider_failure", source=source)


async def _reinstate_voided_commissions(
    db: AsyncSession,
    transaction: Transaction,
) -> None:
    """Return commissions voided by a declined refund to `pending`.

    Only rows still marked `voided` are touched, so a redelivered
    `refund.failed` is a no-op and a commission the clearing task has since
    re-cleared is left alone. A voided commission cannot have been paid — payout
    selection excludes that status — so there is no settled money to unwind.

    Args:
        db: Async SQLAlchemy session, inside the caller's transaction.
        transaction: The purchase whose refund the provider declined.
    """
    commissions = list(
        (
            await db.execute(
                select(PartnerCommission)
                .where(
                    PartnerCommission.transaction_id == transaction.id,
                    PartnerCommission.status == "voided",
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for commission in commissions:
        commission.status = "pending"
        commission.cleared_at = None
        commission.voided_at = None
        await write_audit(
            db=db,
            actor_id=None,
            action="partner_commission_reinstated",
            target_type="partner_commission",
            target_id=commission.id,
            metadata={
                "transaction_id": str(transaction.id),
                "reason": "provider_declined_refund",
            },
        )
        logger.bind(
            module="financials",
            action="partner_commission_reinstated",
            transaction_id=transaction.id,
        ).info("commission_restored_after_failed_refund")
