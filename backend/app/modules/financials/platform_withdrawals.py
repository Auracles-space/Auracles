"""Platform withdrawals: moving the platform's own money to its bank account.

The Paystack balance holds users' money and the platform's together, so a
withdrawal is only allowed up to what Treasury computes as withdrawable, by
the super-admin with step-up (enforced by the router), to a bank account past
its 24-hour hold, and with at most one withdrawal in flight. The transfer
itself runs in a Celery task after commit; the Paystack transfer webhook
settles the outcome.

Maps to: platform treasury design, decisions 2, 4, 8 and 10.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.integrations.payment_failures import normalize_paystack_failure
from app.modules.admin.notifications import notify_admins_review_pending
from app.modules.admin.treasury_schemas import (
    PlatformWithdrawalItem,
    PlatformWithdrawalRequest,
    PlatformWithdrawalsResponse,
)
from app.modules.financials import treasury
from app.modules.financials.models import (
    PlatformBankAccount,
    PlatformConfig,
    PlatformWithdrawal,
)
from app.modules.financials.platform_bank_account import active_platform_bank_account
from app.modules.financials.provider_fees import (
    paystack_transfer_fee_minor,
    record_provider_fee,
)
from app.workers.tasks.platform_withdrawals import process_platform_withdrawal

WITHDRAWAL_CURRENCY = treasury.WITHDRAWABLE_CURRENCY
REFERENCE_PREFIX = "platform-withdrawal-"
MINIMUM_CONFIG_KEY = "min_platform_withdrawal_ngn"
MINIMUM_DEFAULT = Decimal("10000.00")
IN_FLIGHT_STATUSES = ("pending", "processing")
_LOCK_KEY = "platform_treasury:withdrawal"


def _error(status_code: int, error_code: str, message: str) -> HTTPException:
    """Build a typed error with a stable ``error_code``."""
    return HTTPException(
        status_code=status_code,
        detail={"error_code": error_code, "message": message},
    )


def _item(
    withdrawal: PlatformWithdrawal, account: PlatformBankAccount
) -> PlatformWithdrawalItem:
    """Map a withdrawal and its destination to the display-safe response."""
    return PlatformWithdrawalItem(
        id=withdrawal.id,
        amount=withdrawal.amount,
        currency=withdrawal.currency,
        status=withdrawal.status,
        reference=withdrawal.provider_ref,
        bank_name=account.bank_name,
        account_last4=account.account_last4,
        failure_reason=withdrawal.failure_reason,
        awaiting_otp=withdrawal.awaiting_otp,
        requested_by=withdrawal.requested_by,
        requested_at=withdrawal.requested_at,
        completed_at=withdrawal.completed_at,
        failed_at=withdrawal.failed_at,
    )


async def _minimum(db: AsyncSession) -> Decimal:
    """Return the configured withdrawal minimum."""
    configured = await db.scalar(
        select(PlatformConfig.value).where(PlatformConfig.key == MINIMUM_CONFIG_KEY)
    )
    try:
        return Decimal(configured) if configured is not None else MINIMUM_DEFAULT
    except ArithmeticError:
        return MINIMUM_DEFAULT


async def _refuse_insufficient(
    db: AsyncSession,
    *,
    actor_id: UUID,
    amount: Decimal,
    withdrawable: Decimal,
) -> HTTPException:
    """Audit a withdrawal refused for exceeding what is withdrawable.

    Written in its own transaction because the request's transaction is about
    to roll back with the refusal, and a refused attempt to move money must
    still leave a record.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="platform_withdrawal_insufficient_funds",
            target_type="platform_withdrawal",
            metadata={"amount": str(amount), "withdrawable": str(withdrawable)},
        )
    logger.bind(
        module="financials", action="request_platform_withdrawal", user_id=actor_id
    ).warning(
        "platform_withdrawal_insufficient_funds",
        amount=str(amount),
        withdrawable=str(withdrawable),
    )
    return _error(
        status.HTTP_402_PAYMENT_REQUIRED,
        "insufficient_withdrawable",
        f"Only {withdrawable} {WITHDRAWAL_CURRENCY} can be withdrawn right now.",
    )


async def request_platform_withdrawal(
    db: AsyncSession,
    *,
    actor_id: UUID,
    payload: PlatformWithdrawalRequest,
) -> PlatformWithdrawalItem:
    """Record a pending platform withdrawal and queue its transfer.

    The live balance is fetched before the lock so no database lock is held
    across a provider call; user payouts only ever lower the balance and what
    users are owed together, so the figure cannot be inflated in between.

    Args:
        db: Async session.
        actor_id: The super-admin requesting the withdrawal.
        payload: Amount in naira.

    Returns:
        The pending withdrawal.

    Raises:
        HTTPException(422): No bank account, account on hold, or below minimum.
        HTTPException(409): Another withdrawal is already in flight.
        HTTPException(402): Amount exceeds what is withdrawable (audited).
        HTTPException(502): Paystack balance unavailable.
    """
    log = logger.bind(
        module="financials", action="request_platform_withdrawal", user_id=actor_id
    )
    amount = payload.amount.quantize(Decimal("0.01"))
    balances = await treasury.live_balances()
    if balances is None:
        raise _error(
            status.HTTP_502_BAD_GATEWAY,
            "balance_unavailable",
            "Paystack balance is unavailable. Try again shortly.",
        )

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": _LOCK_KEY},
        )
        account = await active_platform_bank_account(db)
        if account is None:
            raise _error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "platform_bank_account_missing",
                "Set the platform bank account first.",
            )
        if account.usable_from > datetime.now(UTC):
            raise _error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "platform_bank_account_on_hold",
                "The platform bank account was changed less than 24 hours ago.",
            )
        in_flight = await db.scalar(
            select(PlatformWithdrawal.id).where(
                PlatformWithdrawal.currency == WITHDRAWAL_CURRENCY,
                PlatformWithdrawal.status.in_(IN_FLIGHT_STATUSES),
            )
        )
        if in_flight is not None:
            raise _error(
                status.HTTP_409_CONFLICT,
                "platform_withdrawal_in_progress",
                "Another withdrawal is still in progress.",
            )
        minimum = await _minimum(db)
        if amount < minimum:
            raise _error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "below_minimum_withdrawal",
                f"The minimum withdrawal is {minimum} {WITHDRAWAL_CURRENCY}.",
            )
        summary = await treasury.currency_summary(
            db, currency=WITHDRAWAL_CURRENCY, balances=balances
        )
        withdrawable = summary.withdrawable or Decimal("0.00")
        if amount > withdrawable:
            refused = True
        else:
            refused = False
            withdrawal_id = uuid4()
            withdrawal = PlatformWithdrawal(
                id=withdrawal_id,
                bank_account_id=account.id,
                amount=amount,
                currency=WITHDRAWAL_CURRENCY,
                status="pending",
                provider_ref=f"{REFERENCE_PREFIX}{withdrawal_id}",
                requested_by=actor_id,
            )
            db.add(withdrawal)
            await db.flush()
            await db.refresh(withdrawal)
            await write_audit(
                db=db,
                actor_id=actor_id,
                action="platform_withdrawal_requested",
                target_type="platform_withdrawal",
                target_id=withdrawal.id,
                metadata={
                    "amount": str(amount),
                    "currency": WITHDRAWAL_CURRENCY,
                    "account_last4": account.account_last4,
                },
            )
            response = _item(withdrawal, account)
    if refused:
        raise await _refuse_insufficient(
            db, actor_id=actor_id, amount=amount, withdrawable=withdrawable
        )

    log.info("platform_withdrawal_requested", amount=str(amount))
    try:
        process_platform_withdrawal.delay(str(response.id))
    except Exception as exc:
        # The pending row is durable; an admin sees it stuck rather than the
        # request pretending nothing happened.
        log.error("platform_withdrawal_dispatch_failed", error=str(exc))
    notify_admins_review_pending(
        domain="platform_withdrawal_requested",
        target_id=response.id,
        title="Platform withdrawal requested",
        body=(
            f"A withdrawal of {amount} {WITHDRAWAL_CURRENCY} to "
            f"{response.bank_name} ****{response.account_last4} was requested."
        ),
        link="/admin/treasury",
    )
    return response


async def list_platform_withdrawals(
    db: AsyncSession, *, page: int, page_size: int
) -> PlatformWithdrawalsResponse:
    """Return platform withdrawal history, newest first.

    Args:
        db: Async session; read only.
        page: 1-based page number.
        page_size: Rows per page (1–100).
    """
    total = await db.scalar(select(func.count()).select_from(PlatformWithdrawal))
    rows = (
        await db.execute(
            select(PlatformWithdrawal, PlatformBankAccount)
            .join(
                PlatformBankAccount,
                PlatformBankAccount.id == PlatformWithdrawal.bank_account_id,
            )
            .order_by(PlatformWithdrawal.requested_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return PlatformWithdrawalsResponse(
        withdrawals=[_item(withdrawal, account) for withdrawal, account in rows],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


async def apply_withdrawal_transfer_outcome(
    db: AsyncSession,
    *,
    reference: str,
    outcome: Literal["completed", "failed"],
    transfer: dict[str, Any],
) -> list[Callable[[], None]] | None:
    """Settle a platform withdrawal from a verified Paystack transfer event.

    The webhook is authoritative in both directions: a success completes even
    a withdrawal the task had given up on (the money did leave, and counting
    it as failed would offer it for withdrawal again), and a reversal fails
    even a completed one (the money came back).

    Args:
        db: Session inside the webhook's transaction.
        reference: The transfer reference from the event.
        outcome: Terminal status the event implies.
        transfer: The event's transfer object.

    Returns:
        Post-commit admin notifications, or None when the reference is not a
        platform withdrawal so the caller can try other payout kinds.
    """
    if not reference.startswith(REFERENCE_PREFIX):
        return None
    withdrawal = await db.scalar(
        select(PlatformWithdrawal)
        .where(PlatformWithdrawal.provider_ref == reference)
        .with_for_update()
    )
    if withdrawal is None:
        return None
    if withdrawal.status == outcome:
        return []

    log = logger.bind(
        module="financials",
        action="settle_platform_withdrawal",
        withdrawal_id=str(withdrawal.id),
    )
    previous_status = withdrawal.status
    now = datetime.now(UTC)
    withdrawal.status = outcome
    withdrawal.awaiting_otp = False
    if outcome == "completed":
        withdrawal.completed_at = now
        fee_minor = paystack_transfer_fee_minor(transfer)
        if fee_minor is not None:
            await record_provider_fee(
                db,
                provider="paystack",
                source_type="platform_withdrawal",
                source_id=withdrawal.id,
                amount_minor=fee_minor,
                currency=withdrawal.currency,
                provider_ref=reference,
                origin="webhook",
            )
        if previous_status == "failed":
            log.critical("platform_withdrawal_completed_after_failure")
        else:
            log.info("platform_withdrawal_completed")
    else:
        withdrawal.failed_at = now
        withdrawal.failure_reason = (
            normalize_paystack_failure(transfer).message
            or "Paystack reported the transfer failed."
        )
        log.error("platform_withdrawal_failed", previous_status=previous_status)

    await write_audit(
        db=db,
        actor_id=None,
        action=f"platform_withdrawal_{outcome}",
        target_type="platform_withdrawal",
        target_id=withdrawal.id,
        metadata={
            "previous_status": previous_status,
            "amount": str(withdrawal.amount),
            "currency": withdrawal.currency,
        },
    )
    withdrawal_id = withdrawal.id
    if outcome == "completed":
        body = (
            f"The platform withdrawal of {withdrawal.amount} {withdrawal.currency} "
            "reached the platform bank account."
        )
        title = "Platform withdrawal completed"
    else:
        body = (
            f"The platform withdrawal of {withdrawal.amount} {withdrawal.currency} "
            f"failed: {withdrawal.failure_reason} The amount is withdrawable again."
        )
        title = "Platform withdrawal failed"
    domain = f"platform_withdrawal_{outcome}"
    return [
        lambda: notify_admins_review_pending(
            domain=domain,
            target_id=withdrawal_id,
            title=title,
            body=body,
            link="/admin/treasury",
        )
    ]
