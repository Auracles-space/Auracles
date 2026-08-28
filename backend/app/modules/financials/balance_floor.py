"""Platform balance floor check for the Paystack rail.

Escrow funded through Paystack lives in the platform's own Paystack balance —
the same balance Contributor payouts draw from. Nothing at the provider marks
held funds as untouchable, so a large payout run (or a provider-side deficit)
could dip the balance below what is currently held in escrow, leaving a future
release impossible to honor.

This check compares the available balance per currency against the sum of
held Paystack-funded escrow and pages an admin the moment the floor is
breached. It never moves money; it exists to surface the breach hours — not
weeks — after it happens.

Maps to: the escrow-in-platform-balance risk accepted in the Paystack escrow
design (Option A).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict
from uuid import NAMESPACE_URL, UUID, uuid5

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import paystack
from app.integrations.amounts import MoneyAmountError, to_minor_units
from app.integrations.paystack import PaystackProviderError
from app.modules.admin.notifications import notify_admins_review_pending
from app.modules.financials.models import Escrow, Transaction


class BalanceFloorResult(TypedDict):
    """Counts from one balance floor run."""

    currencies_checked: int
    alerts: int


def _alert_target_id(currency: str) -> UUID:
    """Return a stable per-currency UUID so repeat alerts dedupe."""
    return uuid5(NAMESPACE_URL, f"auracles:platform-balance-floor:{currency}")


async def check_platform_balance_floor(db: AsyncSession) -> BalanceFloorResult:
    """Alert when the Paystack balance no longer covers held escrow.

    A balance lookup failure leaves the run unresolved rather than guessed
    at: alerting on a transport error would page admins for provider
    downtime, and staying silent hides nothing — the next hourly run retries.

    Args:
        db: Async session; the check only reads.

    Returns:
        Counts of currencies checked and alerts raised.
    """
    held_rows = (
        await db.execute(
            select(
                Escrow.currency,
                func.coalesce(func.sum(Escrow.amount), 0),
            )
            .join(Transaction, Transaction.id == Escrow.transaction_id)
            .where(
                Escrow.status == "held",
                Transaction.provider == "paystack",
            )
            .group_by(Escrow.currency)
        )
    ).all()

    result: BalanceFloorResult = {"currencies_checked": 0, "alerts": 0}
    if not held_rows:
        return result

    try:
        balances = await paystack.fetch_balance()
    except PaystackProviderError as exc:
        logger.bind(
            module="financials",
            action="check_platform_balance_floor",
        ).error("balance_lookup_failed", error=str(exc))
        return result

    for currency, held_total in held_rows:
        result["currencies_checked"] += 1
        held = Decimal(held_total or "0")
        try:
            held_minor = to_minor_units(held, currency)
        except MoneyAmountError:
            logger.bind(
                module="financials",
                action="check_platform_balance_floor",
                currency=currency,
            ).warning("held_escrow_unverifiable_currency")
            continue
        available_minor = balances.get(currency.upper(), 0)
        if available_minor >= held_minor:
            continue

        result["alerts"] += 1
        # CRITICAL: money the platform is contractually holding is not all
        # there. Every payout from this balance deepens the shortfall.
        logger.bind(
            module="financials",
            action="check_platform_balance_floor",
            currency=currency,
        ).critical(
            "platform_balance_below_escrow_floor",
            held_minor=held_minor,
            available_minor=available_minor,
        )
        notify_admins_review_pending(
            domain="platform_balance",
            target_id=_alert_target_id(currency),
            body=(
                f"Paystack balance ({currency} {available_minor} minor units) "
                f"is below the held escrow total ({held_minor} minor units). "
                "Pause payouts and top up the balance before any escrow "
                "release."
            ),
            link="/admin/money",
        )
    return result
