"""Celery task that sends a platform withdrawal through Paystack.

Mirrors the Contributor payout task: the withdrawal's own reference is the
Paystack idempotency key and the value the transfer webhook carries back.
Transient failures retry; once retries are exhausted the withdrawal is marked
failed so its amount returns to withdrawable, and admins are alerted. A failed
withdrawal is never retried automatically (treasury decision 8).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.core.security import decrypt_payout_provider_account_id
from app.integrations import paystack
from app.modules.admin.notifications import notify_admins_review_pending
from app.modules.financials.models import PlatformBankAccount, PlatformWithdrawal
from app.modules.financials.transfer_holds import (
    PAYSTACK_OTP_STATUS,
    alert_transfer_held_for_otp,
)
from app.workers.async_runner import run_async
from app.workers.celery_app import app

_FAILURE_REASON = "Paystack did not accept the transfer."


async def _send_platform_withdrawal(withdrawal_id: str) -> dict[str, str]:
    """Ask Paystack to transfer a pending withdrawal, once.

    Args:
        withdrawal_id: String UUID of the withdrawal.

    Returns:
        The withdrawal id and its resulting status.

    Raises:
        ValueError: No withdrawal matches the id.
        PaystackProviderError: Paystack refused or was unreachable.
    """
    parsed_id = UUID(withdrawal_id)
    async with async_session_factory() as db:
        row = (
            await db.execute(
                select(PlatformWithdrawal, PlatformBankAccount)
                .join(
                    PlatformBankAccount,
                    PlatformBankAccount.id == PlatformWithdrawal.bank_account_id,
                )
                .where(PlatformWithdrawal.id == parsed_id)
            )
        ).one_or_none()
        if row is None:
            raise ValueError("Platform withdrawal not found.")
        withdrawal, account = row
        if withdrawal.status != "pending":
            return {"withdrawal_id": withdrawal_id, "status": withdrawal.status}

        transfer = await paystack.initiate_transfer(
            amount=withdrawal.amount,
            currency=withdrawal.currency,
            recipient=decrypt_payout_provider_account_id(
                account.recipient_code_encrypted
            ),
            reason="Auracles platform withdrawal",
            reference=withdrawal.provider_ref,
        )

        if db.in_transaction():
            await db.rollback()
        async with db.begin():
            locked = await db.get(PlatformWithdrawal, parsed_id, with_for_update=True)
            if locked is None:
                raise ValueError("Platform withdrawal not found.")
            # The webhook may already have settled it; never move it backwards.
            if locked.status == "pending":
                locked.status = "processing"
            held_for_otp = (
                locked.status == "processing"
                and transfer.status == PAYSTACK_OTP_STATUS
            )
            if held_for_otp:
                locked.awaiting_otp = True
            await write_audit(
                db=db,
                actor_id=None,
                action="platform_withdrawal_processing",
                target_type="platform_withdrawal",
                target_id=locked.id,
                metadata={"amount": str(locked.amount), "currency": locked.currency},
            )
            resulting_status = locked.status
            amount = locked.amount
            currency = locked.currency
    if held_for_otp:
        alert_transfer_held_for_otp(
            notify=notify_admins_review_pending,
            what="A platform withdrawal",
            target_id=parsed_id,
            amount=amount,
            currency=currency,
            link="/admin/treasury",
        )
    return {"withdrawal_id": withdrawal_id, "status": resulting_status}


async def _fail_platform_withdrawal_initiation(withdrawal_id: str, error: str) -> None:
    """Mark a still-pending withdrawal failed after its transfer was refused.

    Leaves a withdrawal that already reached ``processing`` alone: Paystack
    accepted that transfer and its webhook decides the outcome.

    Args:
        withdrawal_id: String UUID of the withdrawal.
        error: Provider error text, logged but not stored or shown.
    """
    parsed_id = UUID(withdrawal_id)
    async with async_session_factory() as db:
        async with db.begin():
            withdrawal = await db.get(
                PlatformWithdrawal, parsed_id, with_for_update=True
            )
            if withdrawal is None or withdrawal.status != "pending":
                return
            withdrawal.status = "failed"
            withdrawal.failed_at = datetime.now(UTC)
            withdrawal.failure_reason = _FAILURE_REASON
            await write_audit(
                db=db,
                actor_id=None,
                action="platform_withdrawal_failed",
                target_type="platform_withdrawal",
                target_id=withdrawal.id,
                metadata={"stage": "initiation", "amount": str(withdrawal.amount)},
            )
            amount = withdrawal.amount
            currency = withdrawal.currency
    logger.bind(
        module="financials",
        action="process_platform_withdrawal",
        withdrawal_id=withdrawal_id,
    ).error("platform_withdrawal_initiation_failed", error=error)
    notify_admins_review_pending(
        domain="platform_withdrawal_failed",
        target_id=parsed_id,
        title="Platform withdrawal failed",
        body=(
            f"A platform withdrawal of {amount} {currency} failed: "
            f"{_FAILURE_REASON} The amount is withdrawable again."
        ),
        link="/admin/treasury",
    )


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def process_platform_withdrawal(self: Any, withdrawal_id: str) -> dict[str, str]:
    """Send a pending platform withdrawal, failing it once retries run out."""
    log = logger.bind(
        module="financials",
        action="process_platform_withdrawal",
        task_id=self.request.id,
        withdrawal_id=withdrawal_id,
    )
    log.info("task_started")
    try:
        result = run_async(_send_platform_withdrawal(withdrawal_id))
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            log.error("task_exhausted_retries", error=str(exc))
            run_async(_fail_platform_withdrawal_initiation(withdrawal_id, str(exc)))
            raise
        log.warning("task_retry", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
