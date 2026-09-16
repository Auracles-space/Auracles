"""Monthly Treasury statement for the accountant.

Rebuilds the platform's money and users' money at any past moment from the
timestamps the ledger already keeps (human decision 2026-09-16), so every
past month can be produced without stored snapshots:

- a sale counts when it was made (``transactions.created_at``);
- milestone and attestation commission counts when its escrow was released;
- a refunded sale's commission is reversed when the refund was requested;
- fees, partner commissions and withdrawals count at their own timestamps.

Closing = opening + the month's lines by construction, one month's closing is
the next month's opening, and the latest month matches the live summary.
An escrow counts as held until it was released or refunded
(``refunded_at``); a partner commission counts as a cost from creation and is
handed back in the month it was voided (``voided_at``).

Maps to: platform treasury design §Statement, decision 11.
"""

from __future__ import annotations

import csv
import io
from calendar import monthrange
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.developer.models import PartnerCommission, PartnerPayout
from app.modules.financials.models import (
    Escrow,
    FinancialEvent,
    Payout,
    PlatformBankAccount,
    PlatformWithdrawal,
    ProviderFee,
    Transaction,
)

LAGOS = ZoneInfo("Africa/Lagos")
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_OUTGOING_WITHDRAWAL_STATUSES = ("pending", "processing", "completed")
_COMMISSION_SOURCES = (
    "framework_sales",
    "collections",
    "project_milestones",
    "attestation_fees",
)


def _money(value: Any) -> Decimal:
    """Normalise a SQL sum (or None) to two decimals."""
    return Decimal(value or "0").quantize(_CENT)


def _text(amount: Decimal) -> str:
    """Format an amount as a plain signed decimal for spreadsheets."""
    return f"{amount.quantize(_CENT)}"


def month_bounds(month: str) -> tuple[datetime, datetime]:
    """Return the UTC start and end of a ``YYYY-MM`` month in Lagos time.

    Raises:
        HTTPException(422): The month is malformed or has not started yet.
    """
    try:
        year, month_number = (int(part) for part in month.split("-"))
        start_local = datetime(year, month_number, 1, tzinfo=LAGOS)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error_code": "invalid_month", "message": "Use YYYY-MM."},
        ) from exc
    days = monthrange(year, month_number)[1]
    end_local = start_local + timedelta(days=days)
    start = start_local.astimezone(UTC)
    if start > datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error_code": "month_not_started",
                "message": "That month has not started yet.",
            },
        )
    return start, end_local.astimezone(UTC)


def _in_window(
    moment: Any, start: datetime | None, end: datetime
) -> ColumnElement[bool]:
    """Return ``start <= moment < end`` (open start when None)."""
    conditions = [moment.is_not(None), moment < end]
    if start is not None:
        conditions.append(moment >= start)
    return and_(*conditions)


def _release_date() -> Any:
    """Correlated subquery: when the transaction's escrow was released."""
    return (
        select(func.max(Escrow.released_at))
        .where(
            Escrow.ref_id == Transaction.ref_id,
            Escrow.ref_type == Transaction.ref_type,
            Escrow.status == "released",
        )
        .scalar_subquery()
    )


def _refund_date() -> Any:
    """Correlated subquery: when the transaction's refund was requested."""
    requested = (
        select(func.min(FinancialEvent.occurred_at))
        .where(
            FinancialEvent.entity_type == "transaction",
            FinancialEvent.entity_id == Transaction.id,
            FinancialEvent.event_type == "refund_requested",
        )
        .scalar_subquery()
    )
    return func.coalesce(requested, Transaction.updated_at)


def _credited(start: datetime | None, end: datetime) -> ColumnElement[bool]:
    """Transactions that credited a payee (and earned commission) in a window."""
    return or_(
        and_(
            Transaction.transaction_type == "purchase",
            Transaction.status.in_(("completed", "refunded")),
            _in_window(Transaction.created_at, start, end),
        ),
        and_(
            Transaction.status == "completed",
            or_(
                and_(
                    Transaction.transaction_type == "milestone",
                    Transaction.ref_type == "project_milestone",
                ),
                and_(
                    Transaction.transaction_type == "attestation_fee",
                    Transaction.ref_type == "attestation",
                ),
            ),
            _in_window(_release_date(), start, end),
        ),
    )


def _reversed(start: datetime | None, end: datetime) -> ColumnElement[bool]:
    """Refunded sales whose refund fell in a window."""
    return and_(
        Transaction.transaction_type == "purchase",
        Transaction.status == "refunded",
        _in_window(_refund_date(), start, end),
    )


async def _commission_by_source(
    db: AsyncSession, *, currency: str, start: datetime | None, end: datetime
) -> dict[str, Decimal]:
    """Return commission earned in a window, by source."""
    rows = (
        await db.execute(
            select(
                Transaction.transaction_type,
                Transaction.ref_type,
                func.sum(Transaction.platform_commission),
            )
            .where(Transaction.currency == currency, _credited(start, end))
            .group_by(Transaction.transaction_type, Transaction.ref_type)
        )
    ).all()
    sources = dict.fromkeys(_COMMISSION_SOURCES, _ZERO)
    for transaction_type, ref_type, total in rows:
        if transaction_type == "purchase":
            key = "collections" if ref_type == "collection" else "framework_sales"
        elif transaction_type == "milestone":
            key = "project_milestones"
        else:
            key = "attestation_fees"
        sources[key] += _money(total)
    return sources


async def _scalar_sum(db: AsyncSession, column: Any, *conditions: Any) -> Decimal:
    """Sum one column under conditions."""
    return _money(await db.scalar(select(func.sum(column)).where(*conditions)))


async def _refunded_commission(
    db: AsyncSession, *, currency: str, start: datetime | None, end: datetime
) -> Decimal:
    """Commission taken back by refunds in a window."""
    return await _scalar_sum(
        db,
        Transaction.platform_commission,
        Transaction.currency == currency,
        _reversed(start, end),
    )


async def _fees(
    db: AsyncSession, *, currency: str, start: datetime | None, end: datetime
) -> Decimal:
    """Provider fees charged in a window."""
    return await _scalar_sum(
        db,
        ProviderFee.amount,
        ProviderFee.currency == currency,
        _in_window(ProviderFee.occurred_at, start, end),
    )


async def _partner_commissions(
    db: AsyncSession, *, currency: str, start: datetime | None, end: datetime
) -> Decimal:
    """Partner commissions created in a window, voided or not."""
    return await _scalar_sum(
        db,
        PartnerCommission.commission_amount,
        PartnerCommission.currency == currency,
        _in_window(PartnerCommission.created_at, start, end),
    )


async def _voided_partner_commissions(
    db: AsyncSession, *, currency: str, start: datetime | None, end: datetime
) -> Decimal:
    """Partner commissions voided in a window: cost handed back to the platform."""
    return await _scalar_sum(
        db,
        PartnerCommission.commission_amount,
        PartnerCommission.currency == currency,
        PartnerCommission.status == "voided",
        _in_window(PartnerCommission.voided_at, start, end),
    )


async def _withdrawal_rows(
    db: AsyncSession, *, currency: str, start: datetime | None, end: datetime
) -> list[tuple[PlatformWithdrawal, PlatformBankAccount]]:
    """Withdrawals requested in a window that left, or are leaving, the balance."""
    rows = await db.execute(
        select(PlatformWithdrawal, PlatformBankAccount)
        .join(
            PlatformBankAccount,
            PlatformBankAccount.id == PlatformWithdrawal.bank_account_id,
        )
        .where(
            PlatformWithdrawal.currency == currency,
            PlatformWithdrawal.status.in_(_OUTGOING_WITHDRAWAL_STATUSES),
            _in_window(PlatformWithdrawal.requested_at, start, end),
        )
        .order_by(PlatformWithdrawal.requested_at)
    )
    return [(withdrawal, account) for withdrawal, account in rows.all()]


async def our_money_as_of(
    db: AsyncSession, *, currency: str, moment: datetime
) -> Decimal:
    """Return the platform's own money as it stood at ``moment``."""
    commission = await _commission_by_source(
        db, currency=currency, start=None, end=moment
    )
    withdrawals = await _withdrawal_rows(db, currency=currency, start=None, end=moment)
    return (
        sum(commission.values(), _ZERO)
        - await _refunded_commission(db, currency=currency, start=None, end=moment)
        - await _fees(db, currency=currency, start=None, end=moment)
        - await _partner_commissions(db, currency=currency, start=None, end=moment)
        + await _voided_partner_commissions(
            db, currency=currency, start=None, end=moment
        )
        - sum((withdrawal.amount for withdrawal, _ in withdrawals), _ZERO)
    )


async def _payee_balances_as_of(
    db: AsyncSession,
    *,
    currency: str,
    moment: datetime,
    payee_column: Any,
    payout_column: Any,
) -> Decimal:
    """Total owed to one kind of payee at ``moment``, clamped per payee."""
    credited = (
        await db.execute(
            select(payee_column, func.sum(Transaction.net_amount))
            .where(
                Transaction.currency == currency,
                payee_column.is_not(None),
                _credited(None, moment),
            )
            .group_by(payee_column)
        )
    ).all()
    reversed_rows = (
        await db.execute(
            select(payee_column, func.sum(Transaction.net_amount))
            .where(
                Transaction.currency == currency,
                payee_column.is_not(None),
                _reversed(None, moment),
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
                _in_window(Payout.completed_at, None, moment),
            )
            .group_by(payout_column)
        )
    ).all()
    owed: dict[UUID, Decimal] = {}
    for payee, total in credited:
        owed[payee] = owed.get(payee, _ZERO) + _money(total)
    for payee, total in reversed_rows:
        owed[payee] = owed.get(payee, _ZERO) - _money(total)
    for payee, total in paid_rows:
        owed[payee] = owed.get(payee, _ZERO) - _money(total)
    return sum((max(value, _ZERO) for value in owed.values()), _ZERO)


async def users_money_as_of(
    db: AsyncSession, *, currency: str, moment: datetime
) -> dict[str, Decimal]:
    """Return what users were owed at ``moment``, by line, with the total."""
    held = await _scalar_sum(
        db,
        Escrow.amount,
        Escrow.currency == currency,
        Escrow.held_at < moment,
        or_(
            Escrow.status == "held",
            Escrow.released_at >= moment,
            Escrow.refunded_at >= moment,
        ),
    )
    partner = _money(
        await db.scalar(
            select(func.sum(PartnerCommission.commission_amount))
            .outerjoin(PartnerPayout, PartnerPayout.id == PartnerCommission.payout_id)
            .where(
                PartnerCommission.currency == currency,
                or_(
                    PartnerCommission.status != "voided",
                    PartnerCommission.voided_at >= moment,
                ),
                PartnerCommission.created_at < moment,
                or_(
                    PartnerCommission.payout_id.is_(None),
                    PartnerPayout.status != "completed",
                    PartnerPayout.completed_at.is_(None),
                    PartnerPayout.completed_at >= moment,
                ),
            )
        )
    )
    lines = {
        "held_escrow": held,
        "contributor_balances": await _payee_balances_as_of(
            db,
            currency=currency,
            moment=moment,
            payee_column=Transaction.payee_id,
            payout_column=Payout.contributor_id,
        ),
        "org_balances": await _payee_balances_as_of(
            db,
            currency=currency,
            moment=moment,
            payee_column=Transaction.payee_org_id,
            payout_column=Payout.org_id,
        ),
        "partner_commissions": partner,
    }
    lines["total"] = sum(lines.values(), _ZERO)
    return lines


async def build_statement_csv(db: AsyncSession, *, month: str, currency: str) -> str:
    """Build one month's statement as CSV text.

    Columns: ``section, line, date, reference, amount``. Costs and money
    leaving the platform are negative so the body sums to the movement.
    """
    start, end = month_bounds(month)
    last_day = (end.astimezone(LAGOS) - timedelta(days=1)).date().isoformat()
    first_day = start.astimezone(LAGOS).date().isoformat()

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["section", "line", "date", "reference", "amount"])
    opening = await our_money_as_of(db, currency=currency, moment=start)
    writer.writerow(["opening_balance", "our_money", first_day, "", _text(opening)])
    commission = await _commission_by_source(
        db, currency=currency, start=start, end=end
    )
    for source in _COMMISSION_SOURCES:
        writer.writerow(["commission", source, "", "", _text(commission[source])])
    refunded = await _refunded_commission(db, currency=currency, start=start, end=end)
    writer.writerow(["refunds", "commission_reversed", "", "", _text(-refunded)])
    fees = await _fees(db, currency=currency, start=start, end=end)
    writer.writerow(["provider_fees", "paystack", "", "", _text(-fees)])
    partner = await _partner_commissions(db, currency=currency, start=start, end=end)
    writer.writerow(
        ["partner_commissions", "partner_commissions", "", "", _text(-partner)]
    )
    voided = await _voided_partner_commissions(
        db, currency=currency, start=start, end=end
    )
    writer.writerow(["partner_commissions", "voided", "", "", _text(voided)])
    for withdrawal, account in await _withdrawal_rows(
        db, currency=currency, start=start, end=end
    ):
        writer.writerow(
            [
                "withdrawal",
                f"{withdrawal.status} ****{account.account_last4}",
                withdrawal.requested_at.astimezone(LAGOS).date().isoformat(),
                withdrawal.provider_ref,
                _text(-withdrawal.amount),
            ]
        )
    closing = await our_money_as_of(db, currency=currency, moment=end)
    writer.writerow(["closing_balance", "our_money", last_day, "", _text(closing)])
    for line, amount in (
        await users_money_as_of(db, currency=currency, moment=end)
    ).items():
        writer.writerow(["users_money", line, last_day, "", _text(amount)])
    return output.getvalue()


async def download_statement(
    db: AsyncSession, *, month: str, currency: str, actor_id: UUID
) -> str:
    """Build a statement and audit that an admin downloaded it.

    Raises:
        HTTPException(422): Malformed or not-yet-started month.
    """
    body = await build_statement_csv(db, month=month, currency=currency)
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="treasury_statement_downloaded",
            target_type="treasury_statement",
            metadata={"month": month, "currency": currency},
        )
    return body
