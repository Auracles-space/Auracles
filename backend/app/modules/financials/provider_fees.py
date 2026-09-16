"""Provider fee recording for platform treasury.

The platform absorbs payment provider fees (treasury decision 6), so every fee
Paystack keeps is a platform cost. This module is the single write path into
``provider_fees``; webhooks and the one-off backfill both go through it so the
idempotency rule lives in one place.

Maps to: FR-FIN-* (platform treasury).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from loguru import logger
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.financials.models import ProviderFee

FeeSourceType = Literal[
    "transaction", "payout", "partner_payout", "platform_withdrawal"
]
FeeOrigin = Literal["webhook", "backfill"]


async def record_provider_fee(
    db: AsyncSession,
    *,
    provider: Literal["stripe", "paystack"],
    source_type: FeeSourceType,
    source_id: UUID,
    amount_minor: int,
    currency: str,
    provider_ref: str,
    origin: FeeOrigin,
    occurred_at: datetime | None = None,
) -> bool:
    """Record one provider fee, ignoring a fee already recorded for the reference.

    Runs inside the caller's transaction so a fee is only durable when the
    event that carried it is. A non-positive amount records nothing, because
    a missing or zero fee is not a cost.

    Args:
        db: Session inside the caller's transaction.
        provider: Rail that kept the fee.
        source_type: Kind of record the fee was charged on.
        source_id: Id of that record.
        amount_minor: Fee in provider minor units (kobo or cents).
        currency: ISO 4217 currency of the fee.
        provider_ref: Charge reference or transfer code the fee belongs to.
        origin: Whether a webhook or the backfill found the fee.
        occurred_at: Provider-side time of the charge; defaults to now.

    Returns:
        True when a new fee row was written, False otherwise.
    """
    if amount_minor <= 0:
        return False
    statement = (
        insert(ProviderFee)
        .values(
            provider=provider,
            source_type=source_type,
            source_id=source_id,
            amount=Decimal(amount_minor) / Decimal(100),
            currency=currency.strip().upper(),
            provider_ref=provider_ref,
            origin=origin,
            occurred_at=occurred_at if occurred_at is not None else func.now(),
        )
        .on_conflict_do_nothing(constraint="uq_provider_fees_provider_source_ref")
        .returning(ProviderFee.id)
    )
    fee_id = await db.scalar(statement)
    if fee_id is not None:
        logger.bind(
            module="financials",
            action="record_provider_fee",
            source_type=source_type,
            source_id=str(source_id),
        ).info("provider_fee_recorded", provider=provider, origin=origin)
    return fee_id is not None


def paystack_transfer_fee_minor(transfer: dict[str, Any]) -> int | None:
    """Return the fee Paystack charged on a transfer, in kobo, if reported.

    Paystack reports it as ``fee_charged`` on transfer objects. Treasury open
    item A: confirm against a live test-mode ``transfer.success`` payload; the
    balance-gap warning surfaces any fee this misses.
    """
    fee = transfer.get("fee_charged")
    return fee if isinstance(fee, int) and fee > 0 else None
