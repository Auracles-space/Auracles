"""Platform treasury summary.

Answers, per currency, how much of the money the platform holds belongs to
users, how much is the platform's own, and how much of the platform's share
can be withdrawn right now. Paystack keeps every collected naira in one
balance, so the withdrawable figure is capped by both the platform's ledger
share and what the live balance can spare after everything users are owed.

Payee balances reuse ``financials.service.earning_class_filter`` and the
payout claim rules, so Treasury never holds a second definition of what a
user has earned.

Maps to: platform treasury design §Definitions (FR-FIN-*, FR-ADMIN-*).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.integrations import paystack
from app.integrations.paystack import PaystackProviderError
from app.modules.admin.treasury_schemas import (
    TreasuryCurrencySummary,
    TreasuryOurMoney,
    TreasuryOwedToUsers,
    TreasurySummaryResponse,
)
from app.modules.developer.models import PartnerCommission, PartnerPayout
from app.modules.financials.models import (
    Escrow,
    Payout,
    PlatformWithdrawal,
    ProviderFee,
    Transaction,
)
from app.modules.financials.service import (
    _ATTESTATION_EARNING_CLASS,
    _MARKETPLACE_EARNING_CLASS,
    earning_class_filter,
)

# Paystack holds only naira for the platform; every other currency settles on
# Stripe and is reported from the ledger alone (treasury decision 1).
WITHDRAWABLE_CURRENCY = "NGN"
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


def _money(value: Any) -> Decimal:
    """Normalise a SQL sum (or None) to a two-decimal Decimal."""
    return Decimal(value or "0").quantize(_CENT)


def _settled_earning_filter() -> Any:
    """Return the predicate for completed transactions that credit a payee."""
    return (Transaction.status == "completed") & or_(
        earning_class_filter(_MARKETPLACE_EARNING_CLASS),
        earning_class_filter(_ATTESTATION_EARNING_CLASS),
    )


async def _payee_balances(
    db: AsyncSession,
    *,
    currency: str,
    payee_column: InstrumentedAttribute[UUID | None],
    payout_column: InstrumentedAttribute[UUID | None],
) -> Decimal:
    """Return the total still owed to one kind of payee (individual or org).

    Owed = net earned − payouts that completed. Payouts still pending or
    processing have not left the balance, so they remain owed. Each payee is
    clamped at zero, matching the per-account available balance, so one
    over-drawn payee never hides money owed to another.
    """
    earned_rows = (
        await db.execute(
            select(payee_column, func.sum(Transaction.net_amount))
            .where(
                _settled_earning_filter(),
                Transaction.currency == currency,
                payee_column.is_not(None),
            )
            .group_by(payee_column)
        )
    ).all()
    paid_rows = (
        await db.execute(
            select(payout_column, func.sum(Payout.net_amount))
            .where(
                Payout.currency == currency,
                Payout.status == "completed",
                payout_column.is_not(None),
            )
            .group_by(payout_column)
        )
    ).all()
    paid = {payee: _money(total) for payee, total in paid_rows}
    return sum(
        (
            max(_money(total) - paid.get(payee, _ZERO), _ZERO)
            for payee, total in earned_rows
        ),
        _ZERO,
    )


async def _held_escrow(db: AsyncSession, *, currency: str) -> Decimal:
    """Return funds held in escrow, not yet anyone's to keep."""
    return _money(
        await db.scalar(
            select(func.sum(Escrow.amount)).where(
                Escrow.status == "held", Escrow.currency == currency
            )
        )
    )


async def _unpaid_partner_commissions(db: AsyncSession, *, currency: str) -> Decimal:
    """Return partner commissions earned but not yet paid out."""
    return _money(
        await db.scalar(
            select(func.sum(PartnerCommission.commission_amount))
            .outerjoin(PartnerPayout, PartnerPayout.id == PartnerCommission.payout_id)
            .where(
                PartnerCommission.currency == currency,
                PartnerCommission.status.in_(("pending", "cleared")),
                or_(
                    PartnerCommission.payout_id.is_(None),
                    PartnerPayout.status != "completed",
                ),
            )
        )
    )


async def _commission_by_source(
    db: AsyncSession, *, currency: str
) -> dict[str, Decimal]:
    """Return platform commission earned on settled transactions, by source."""
    rows = (
        await db.execute(
            select(
                Transaction.transaction_type,
                Transaction.ref_type,
                func.sum(Transaction.platform_commission),
            )
            .where(_settled_earning_filter(), Transaction.currency == currency)
            .group_by(Transaction.transaction_type, Transaction.ref_type)
        )
    ).all()
    sources = {
        "framework_sales": _ZERO,
        "collections": _ZERO,
        "project_milestones": _ZERO,
        "attestation_fees": _ZERO,
    }
    for transaction_type, ref_type, total in rows:
        if transaction_type == "purchase":
            key = "collections" if ref_type == "collection" else "framework_sales"
        elif transaction_type == "milestone":
            key = "project_milestones"
        else:
            key = "attestation_fees"
        sources[key] += _money(total)
    return sources


async def _total_partner_commissions(db: AsyncSession, *, currency: str) -> Decimal:
    """Return partner commissions funded from platform commission (not voided)."""
    return _money(
        await db.scalar(
            select(func.sum(PartnerCommission.commission_amount)).where(
                PartnerCommission.currency == currency,
                PartnerCommission.status != "voided",
            )
        )
    )


async def _provider_fees(db: AsyncSession, *, currency: str) -> Decimal:
    """Return provider fees the platform absorbed."""
    return _money(
        await db.scalar(
            select(func.sum(ProviderFee.amount)).where(ProviderFee.currency == currency)
        )
    )


async def _platform_withdrawals(db: AsyncSession, *, currency: str) -> Decimal:
    """Return platform withdrawals that have left, or are leaving, the balance.

    Pending and processing count as gone so a second withdrawal can never be
    sized against money already on its way out; failed ones do not count.
    """
    return _money(
        await db.scalar(
            select(func.sum(PlatformWithdrawal.amount)).where(
                PlatformWithdrawal.currency == currency,
                PlatformWithdrawal.status.in_(("pending", "processing", "completed")),
            )
        )
    )


async def _currencies(db: AsyncSession) -> list[str]:
    """Return the withdrawable currency first, then every other ledger currency."""
    rows: Iterable[str] = (
        await db.scalars(select(Transaction.currency).distinct())
    ).all()
    others = sorted({code.upper() for code in rows} - {WITHDRAWABLE_CURRENCY})
    return [WITHDRAWABLE_CURRENCY, *others]


async def live_balances() -> dict[str, int] | None:
    """Fetch the live Paystack balance, or None when Paystack cannot answer."""
    try:
        return await paystack.fetch_balance()
    except PaystackProviderError as exc:
        logger.bind(module="financials", action="treasury_summary").error(
            "treasury_balance_lookup_failed", error=str(exc)
        )
        return None


async def currency_summary(
    db: AsyncSession,
    *,
    currency: str,
    balances: dict[str, int] | None,
) -> TreasuryCurrencySummary:
    """Build one currency's Treasury block."""
    owed = TreasuryOwedToUsers(
        held_escrow=await _held_escrow(db, currency=currency),
        contributor_balances=await _payee_balances(
            db,
            currency=currency,
            payee_column=Transaction.payee_id,
            payout_column=Payout.contributor_id,
        ),
        org_balances=await _payee_balances(
            db,
            currency=currency,
            payee_column=Transaction.payee_org_id,
            payout_column=Payout.org_id,
        ),
        partner_commissions=await _unpaid_partner_commissions(db, currency=currency),
        total=_ZERO,
    )
    owed.total = (
        owed.held_escrow
        + owed.contributor_balances
        + owed.org_balances
        + owed.partner_commissions
    )

    commission = await _commission_by_source(db, currency=currency)
    ours = TreasuryOurMoney(
        commission_framework_sales=commission["framework_sales"],
        commission_collections=commission["collections"],
        commission_project_milestones=commission["project_milestones"],
        commission_attestation_fees=commission["attestation_fees"],
        provider_fees=await _provider_fees(db, currency=currency),
        partner_commissions=await _total_partner_commissions(db, currency=currency),
        platform_withdrawals=await _platform_withdrawals(db, currency=currency),
        total=_ZERO,
    )
    ours.total = (
        sum(commission.values(), _ZERO)
        - ours.provider_fees
        - ours.partner_commissions
        - ours.platform_withdrawals
    )

    withdrawable_here = currency == WITHDRAWABLE_CURRENCY
    live_balance: Decimal | None = None
    withdrawable: Decimal | None = None
    balance_gap: Decimal | None = None
    if withdrawable_here and balances is not None:
        live_balance = (Decimal(balances.get(currency, 0)) / 100).quantize(_CENT)
        spare = live_balance - owed.total
        withdrawable = max(min(ours.total, spare), _ZERO).quantize(
            _CENT, rounding=ROUND_DOWN
        )
        balance_gap = live_balance - (owed.total + ours.total)

    return TreasuryCurrencySummary(
        currency=currency,
        withdrawable_here=withdrawable_here,
        owed_to_users=owed,
        our_money=ours,
        live_balance=live_balance,
        withdrawable=withdrawable,
        balance_gap=balance_gap,
        balance_unavailable=withdrawable_here and balances is None,
    )


async def get_treasury_summary(db: AsyncSession) -> TreasurySummaryResponse:
    """Return the Treasury summary for every currency on the ledger.

    A Paystack balance outage still returns every ledger figure; only the
    live balance, withdrawable amount and gap are withheld, because guessing
    them could let the platform withdraw users' money.

    Args:
        db: Async session; the summary only reads.

    Returns:
        One block per currency, the withdrawable currency first.
    """
    balances = await live_balances()
    fetched_at = datetime.now(UTC) if balances is not None else None
    currencies = [
        await currency_summary(db, currency=currency, balances=balances)
        for currency in await _currencies(db)
    ]
    return TreasurySummaryResponse(
        currencies=currencies, live_balance_fetched_at=fetched_at
    )
