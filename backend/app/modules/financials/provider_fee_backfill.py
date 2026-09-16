"""One-off backfill of Paystack fees on charges settled before fee recording.

Slice 1 records each charge's fee from its webhook. Charges settled earlier
have no fee row, so Treasury would overstate the platform's money. The
backfill looks each settled Paystack charge up once by reference, records the
fee Paystack reports as a backfilled cost dated when the charge was paid, and
is safe to rerun: charges with a fee row are skipped and recording itself is
idempotent (treasury decision 7).

Maps to: platform treasury design, decision 7.
"""

from __future__ import annotations

import asyncio
from typing import TypedDict
from uuid import UUID

from loguru import logger
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.integrations import paystack
from app.integrations.paystack import PaystackProviderError
from app.modules.financials.models import ProviderFee, Transaction
from app.modules.financials.provider_fees import record_provider_fee
from app.workers.tasks.provider_fee_backfill import backfill_provider_fees

# Charge-bearing transaction types; refund rows are money going back out.
_CHARGE_TYPES = ("purchase", "milestone", "attestation_fee")
# A refunded charge was still paid, and Paystack kept its fee.
_SETTLED_STATUSES = ("completed", "refunded")
# Stay well under Paystack's API rate limit.
_LOOKUP_INTERVAL_SECONDS = 0.2


class BackfillResult(TypedDict):
    """Counts from one backfill run."""

    checked: int
    recorded: int
    failed: int


async def _charges_without_fees() -> list[tuple[UUID, str]]:
    """Return one (transaction id, reference) per settled charge lacking a fee.

    Grouped by reference because an escrow split's release row reuses the
    funding charge's reference; the fee belongs to the charge, once.
    """
    has_fee = exists(
        select(ProviderFee.id).where(
            ProviderFee.provider == "paystack",
            ProviderFee.source_type == "transaction",
            ProviderFee.provider_ref == Transaction.provider_ref,
        )
    )
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(Transaction.id, Transaction.provider_ref)
                .where(
                    Transaction.provider == "paystack",
                    Transaction.transaction_type.in_(_CHARGE_TYPES),
                    Transaction.status.in_(_SETTLED_STATUSES),
                    Transaction.provider_ref.is_not(None),
                    ~has_fee,
                )
                .order_by(Transaction.created_at)
            )
        ).all()
    first_by_reference: dict[str, UUID] = {}
    for transaction_id, reference in rows:
        first_by_reference.setdefault(reference, transaction_id)
    return [(tid, ref) for ref, tid in first_by_reference.items()]


async def backfill_paystack_fees() -> BackfillResult:
    """Look up and record the fee for every settled Paystack charge without one.

    A failed lookup is counted and skipped so one bad charge cannot stop the
    run; a later run retries it.

    Returns:
        How many charges were checked, how many fees were recorded, and how
        many lookups failed.
    """
    log = logger.bind(module="financials", action="backfill_provider_fees")
    result: BackfillResult = {"checked": 0, "recorded": 0, "failed": 0}
    for transaction_id, reference in await _charges_without_fees():
        result["checked"] += 1
        try:
            charge = await paystack.fetch_transaction(reference=reference)
        except PaystackProviderError as exc:
            result["failed"] += 1
            log.warning(
                "fee_lookup_failed",
                transaction_id=str(transaction_id),
                error=str(exc),
            )
            await asyncio.sleep(_LOOKUP_INTERVAL_SECONDS)
            continue
        if charge.fees_minor and charge.currency:
            async with async_session_factory() as db:
                async with db.begin():
                    if await record_provider_fee(
                        db,
                        provider="paystack",
                        source_type="transaction",
                        source_id=transaction_id,
                        amount_minor=charge.fees_minor,
                        currency=charge.currency,
                        provider_ref=reference,
                        origin="backfill",
                        occurred_at=charge.paid_at,
                    ):
                        result["recorded"] += 1
        await asyncio.sleep(_LOOKUP_INTERVAL_SECONDS)
    log.info("fee_backfill_finished", **result)
    return result


async def request_fee_backfill(db: AsyncSession, *, actor_id: UUID) -> None:
    """Audit and queue a fee backfill run for the super-admin.

    Args:
        db: Async session.
        actor_id: The super-admin requesting the run.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="provider_fee_backfill_requested",
            target_type="provider_fee",
        )
    backfill_provider_fees.delay(str(actor_id))
