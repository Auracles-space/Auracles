"""Celery tasks for Contributor payout processing.

Payouts settle on the rail their payout account was registered on: Stripe
Connect transfers for connected accounts, Paystack transfers for Nigerian
NUBAN recipients. The provider is read from the account row rather than a
global setting, because a recipient code issued by one provider means nothing
to the other.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.core.security import decrypt_payout_provider_account_id
from app.integrations import paystack, stripe
from app.integrations.paystack import PaystackProviderError
from app.modules.admin.notifications import notify_admins_review_pending
from app.modules.financials.models import Payout, PayoutAccount
from app.modules.financials.transfer_holds import (
    PAYSTACK_OTP_STATUS,
    alert_transfer_held_for_otp,
)
from app.workers.async_runner import run_async
from app.workers.celery_app import app

# Reason stamped on a payout the platform balance cannot yet fund. Narrow on
# purpose: it names a condition the beneficiary can neither cause nor fix,
# which is the only kind of wait worth explaining to them.
INSUFFICIENT_BALANCE_REASON = "insufficient_platform_balance"


async def _defer_payout(
    *, payout_id: UUID, amount: Decimal, currency: str
) -> dict[str, str]:
    """Leave a payout pending with the reason it could not be sent yet.

    The payout keeps its `pending` status so the hourly sweeper retries it;
    only the reason is added. Admins are alerted because a platform shortfall
    is theirs to resolve, and the beneficiary can do nothing about it.

    Args:
        payout_id: Payout that could not be funded.
        amount: Net amount that was attempted, for the alert.
        currency: Currency of that amount.

    Returns:
        The task result, reporting the payout as deferred.
    """
    log = logger.bind(
        module="financials", action="defer_payout", payout_id=str(payout_id)
    )
    async with async_session_factory() as db:
        async with db.begin():
            payout = await db.get(Payout, payout_id, with_for_update=True)
            if payout is None:
                raise ValueError("Payout not found.")
            already_known = payout.delay_reason == INSUFFICIENT_BALANCE_REASON
            payout.delay_reason = INSUFFICIENT_BALANCE_REASON

    # WARNING, not ERROR: nothing is broken and the retry will clear it, but
    # money owed to a user is not moving and somebody should know.
    log.warning("payout_deferred_for_platform_balance")
    # Alert once per payout, not once per hourly retry, or a shortfall
    # lasting a weekend would page admins forty times about one payout.
    if not already_known:
        notify_admins_review_pending(
            domain="payout",
            target_id=payout_id,
            body=(
                f"A payout of {amount} {currency} cannot be sent yet because "
                "the platform balance does not cover it. It stays queued and "
                "goes out automatically once the balance recovers, but the "
                "beneficiary is waiting and their earnings stay locked until "
                "it does."
            ),
            link="/admin/payouts",
        )
    return {
        "payout_id": str(payout_id),
        "provider_ref": "",
        "status": "deferred",
    }


async def _process_payout_transfer(payout_id: str) -> dict[str, str]:
    """Create a provider transfer for a pending payout request.

    Idempotent by design: a payout already carrying a provider reference is
    returned untouched, so a Celery retry cannot send the money twice.

    Args:
        payout_id: String UUID of the payout to process.

    Returns:
        The payout id, its provider reference, and its resulting status.

    Raises:
        ValueError: If no payout row matches the id.
    """
    parsed_payout_id = UUID(payout_id)
    async with async_session_factory() as db:
        row = await db.execute(
            select(Payout, PayoutAccount)
            .join(PayoutAccount, PayoutAccount.id == Payout.payout_account_id)
            .where(Payout.id == parsed_payout_id)
        )
        result = row.one_or_none()
        if result is None:
            raise ValueError("Payout not found.")
        payout, payout_account = result
        if payout.status in {"processing", "completed"} and payout.provider_ref:
            return {
                "payout_id": str(payout.id),
                "provider_ref": payout.provider_ref,
                "status": payout.status,
            }
        if payout.status != "pending":
            return {
                "payout_id": str(payout.id),
                "provider_ref": payout.provider_ref or "",
                "status": payout.status,
            }

        # Beneficiary is exactly one of a Contributor or an Organization
        # (XOR on the payout row); tag the transfer with whichever is set.
        beneficiary_meta = (
            {"contributor_id": str(payout.contributor_id)}
            if payout.contributor_id is not None
            else {"org_id": str(payout.org_id)}
        )
        destination_account_id = decrypt_payout_provider_account_id(
            payout_account.provider_account_id
        )
        # The rail comes from the payout account, never from a global setting.
        # A recipient code issued by one provider is meaningless to the other,
        # so a mismatch would address the money nowhere.
        provider = payout_account.provider

        held_for_otp = False
        if provider == "paystack":
            # Our own reference, not Paystack's id, is the durable handle: it
            # is the idempotency key for a retried transfer AND the only value
            # the `transfer.success` webhook carries back that we can match a
            # payout row on. Paystack's numeric id is not known until after the
            # call, so it cannot serve either purpose.
            reference = f"payout-{payout.id}"
            try:
                paystack_transfer = await paystack.initiate_transfer(
                    amount=payout.net_amount,
                    currency=payout.currency,
                    recipient=destination_account_id,
                    reason="Auracles payout",
                    reference=reference,
                )
            except PaystackProviderError as exc:
                if not exc.insufficient_balance:
                    raise
                # The platform balance cannot cover this yet. Leaving the
                # payout at `pending` is deliberate: the hourly sweeper
                # retries it, and it goes through untouched once money
                # settles. What was missing is the reason, without which the
                # beneficiary sees only an unexplained wait.
                return await _defer_payout(
                    payout_id=parsed_payout_id,
                    amount=payout.net_amount,
                    currency=payout.currency,
                )
            provider_ref = reference
            audit_ref = paystack_transfer.transfer_code or reference
            held_for_otp = paystack_transfer.status == PAYSTACK_OTP_STATUS
        else:
            stripe_transfer = await stripe.create_transfer(
                amount=payout.net_amount,
                currency=payout.currency,
                destination_account_id=destination_account_id,
                metadata={
                    "payout_id": str(payout.id),
                    **beneficiary_meta,
                },
                idempotency_key=f"payout:{payout.id}",
            )
            provider_ref = stripe_transfer.id
            audit_ref = stripe_transfer.id

        if db.in_transaction():
            await db.rollback()
        async with db.begin():
            payout = await db.get(Payout, parsed_payout_id)
            if payout is None:
                raise ValueError("Payout not found.")
            payout.status = "processing"
            payout.provider_ref = provider_ref
            payout.awaiting_otp = held_for_otp
            # The wait is over, so its reason must not outlive it: a retry
            # that succeeds after a shortfall would otherwise keep telling
            # the beneficiary the balance is short.
            payout.delay_reason = None
            await write_audit(
                db=db,
                actor_id=payout.contributor_id,
                action="payout_processing",
                target_type="payout",
                target_id=payout.id,
                metadata={
                    "provider": provider,
                    "transfer_ref": audit_ref[-4:],
                    "net_amount": str(payout.net_amount),
                },
            )
            payout_amount = payout.net_amount
            payout_currency = payout.currency
        if held_for_otp:
            alert_transfer_held_for_otp(
                notify=notify_admins_review_pending,
                what="A payout",
                target_id=parsed_payout_id,
                amount=payout_amount,
                currency=payout_currency,
                link="/admin/payouts",
            )
        return {
            "payout_id": str(parsed_payout_id),
            "provider_ref": provider_ref,
            "status": "processing",
        }


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def process_payout(self: Any, payout_id: str) -> dict[str, str]:
    """Process a pending payout by creating a transfer on its own rail."""
    log = logger.bind(
        module="financials",
        action="process_payout",
        task_id=self.request.id,
        payout_id=payout_id,
    )
    log.info("task_started")
    try:
        result = run_async(_process_payout_transfer(payout_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
