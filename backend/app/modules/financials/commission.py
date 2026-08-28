"""Sale-time commission snapshot.

The platform's cut of each sale is locked at the moment the money settles:
`transactions.platform_commission` and `net_amount` are stamped when a
purchase completes or an escrow funding is held, so a later change to the
admin-configured rate cannot reprice earnings a Contributor has already made.
Balances and payouts read the stamped values; the configured rates here are
consulted only at settlement time.

Lives outside `service.py` so `escrow_service` (which completes milestone and
attestation-fee transactions) can stamp without importing the service layer.

Maps to: BR-FIN-001 (commission deducted at payout, at the sale-time rate).
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.financials.models import PlatformConfig, Transaction

MARKETPLACE_COMMISSION_DEFAULT = Decimal("0.15")
ATTESTATION_COMMISSION_DEFAULT = Decimal("0.10")

# Transaction types whose completion stamps the marketplace rate. Attestation
# fees settle at their own lower rate (Module 6a design §4.1).
_MARKETPLACE_TYPES = frozenset({"purchase", "milestone"})


def _normalise_money(amount: Decimal) -> Decimal:
    """Return a two-decimal money value for stamped commission columns."""
    return amount.quantize(Decimal("0.01"))


async def _decimal_config(
    db: AsyncSession,
    *,
    key: str,
    default: Decimal,
) -> Decimal:
    """Return a decimal platform configuration value."""
    configured = await db.scalar(
        select(PlatformConfig.value).where(PlatformConfig.key == key)
    )
    if configured is None:
        return default
    try:
        return Decimal(configured)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{key} configuration is invalid.",
        ) from exc


async def marketplace_commission_rate(db: AsyncSession) -> Decimal:
    """Return the configured marketplace commission rate."""
    return await _decimal_config(
        db,
        key="commission_rate",
        default=MARKETPLACE_COMMISSION_DEFAULT,
    )


async def attestation_commission_rate(db: AsyncSession) -> Decimal:
    """Return the configured Attestation settlement commission rate."""
    return await _decimal_config(
        db,
        key="attestation_commission_rate",
        default=ATTESTATION_COMMISSION_DEFAULT,
    )


async def rate_for_transaction(
    db: AsyncSession,
    transaction: Transaction,
) -> Decimal:
    """Return the commission rate a settling transaction stamps.

    Raises:
        ValueError: The transaction type never carries seller commission
            (refunds, payouts) — stamping it would corrupt the money record.
    """
    if transaction.transaction_type in _MARKETPLACE_TYPES:
        return await marketplace_commission_rate(db)
    if transaction.transaction_type == "attestation_fee":
        return await attestation_commission_rate(db)
    raise ValueError(
        f"Transaction type {transaction.transaction_type!r} does not stamp "
        "commission."
    )


def stamp_commission(transaction: Transaction, rate: Decimal) -> None:
    """Write the sale-time commission split onto a settling transaction.

    Idempotent under replay only while the rate is unchanged, so callers
    stamp exactly once — on the transition into `completed` — and never on a
    redelivered settlement event.
    """
    commission = _normalise_money(transaction.amount * rate)
    transaction.platform_commission = commission
    transaction.net_amount = _normalise_money(transaction.amount - commission)


async def stamp_settling_transaction(
    db: AsyncSession,
    transaction: Transaction,
) -> None:
    """Look up the type-appropriate rate and stamp a settling transaction."""
    rate = await rate_for_transaction(db, transaction)
    stamp_commission(transaction, rate)
