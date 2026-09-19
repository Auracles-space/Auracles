"""Reconcile Paystack transfers that are held for a one-time code.

A transfer waiting on an OTP produces no webhook, and Paystack abandons it
about an hour later — also without a webhook. Nothing else in the system ever
revisits the payout, so its row stays at ``processing`` indefinitely.

That is not cosmetic. While a payout sits at ``processing`` the beneficiary is
refused another payout as one already in flight, and the amount stays counted
against their available balance. A single unanswered code therefore locks a
contributor out of their own earnings for money that will never be sent. This
task closes that gap by asking the provider what actually happened.

It is deliberately not limited to the OTP case in spirit: any transfer the
provider ends without telling us would strand the same way, and asking is the
only remedy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.integrations import paystack
from app.integrations.paystack import PaystackProviderError
from app.modules.admin.notifications import notify_admins_review_pending
from app.modules.financials.ledger import record_financial_event
from app.modules.financials.models import Payout, PlatformWithdrawal
from app.modules.financials.platform_withdrawals import (
    apply_withdrawal_transfer_outcome,
)
from app.modules.financials.provider_fees import (
    paystack_transfer_fee_minor,
    record_provider_fee,
)
from app.workers.async_runner import run_async
from app.workers.celery_app import app

# Statuses meaning Paystack will never send this transfer. "abandoned" is the
# one that follows an unanswered OTP; the others are included because they end
# the transfer the same way and leave the row equally stranded.
DEAD_TRANSFER_STATUSES = {"abandoned", "failed", "reversed"}
# Status meaning the money did leave, and we simply never saw the webhook.
SETTLED_TRANSFER_STATUS = "success"


def _outcome_for(transfer_status: str) -> str | None:
    """Map a provider transfer status to the outcome it settles, if any."""
    if transfer_status == SETTLED_TRANSFER_STATUS:
        return "completed"
    if transfer_status in DEAD_TRANSFER_STATUSES:
        return "failed"
    return None


async def _reconcile_held_transfers() -> dict[str, int]:
    """Ask Paystack what became of every transfer held for a code.

    Covers both kinds of transfer the platform makes — contributor and org
    payouts, and platform withdrawals — because both record `awaiting_otp` and
    both strand the same way when no webhook ever follows.

    Returns:
        How many held transfers were checked and how many changed state.
    """
    checked = 0
    reconciled = 0

    async with async_session_factory() as db:
        held = (
            (
                await db.execute(
                    select(Payout).where(
                        Payout.awaiting_otp.is_(True),
                        Payout.status.in_(("pending", "processing")),
                    )
                )
            )
            .scalars()
            .all()
        )
        held_ids = [(payout.id, payout.provider_ref) for payout in held]

    for payout_id, provider_ref in held_ids:
        log = logger.bind(
            module="financials",
            action="reconcile_held_transfer",
            target_id=str(payout_id),
        )
        if not provider_ref:
            # Nothing to ask about: the transfer never reached the provider.
            log.warning("held_payout_has_no_provider_reference")
            continue

        checked += 1
        try:
            transfer = await paystack.verify_transfer(reference=provider_ref)
        except PaystackProviderError as exc:
            # Leave the payout held and try again next run rather than failing
            # a transfer that may still be alive.
            log.error("transfer_verify_failed: {error}", error=str(exc))
            continue

        transfer_status = str(transfer.get("status"))
        outcome = _outcome_for(transfer_status)
        if outcome is None:
            log.info("transfer_still_held", transfer_status=transfer_status)
            continue

        if await _settle_payout(
            payout_id=payout_id,
            outcome=outcome,
            transfer_status=transfer_status,
            transfer=transfer,
        ):
            reconciled += 1
            log.info("held_transfer_reconciled", outcome=outcome)

    withdrawal_counts = await _reconcile_held_withdrawals()
    return {
        "checked": checked + withdrawal_counts["checked"],
        "reconciled": reconciled + withdrawal_counts["reconciled"],
    }


async def _reconcile_held_withdrawals() -> dict[str, int]:
    """Settle platform withdrawals the provider ended without a webhook.

    Settlement goes through the same function the webhook uses, so a
    withdrawal reconciled here records the provider fee and the ledger rows
    exactly as a delivered webhook would have.

    Returns:
        How many held withdrawals were checked and how many changed state.
    """
    checked = 0
    reconciled = 0

    async with async_session_factory() as db:
        held = (
            (
                await db.execute(
                    select(PlatformWithdrawal).where(
                        PlatformWithdrawal.awaiting_otp.is_(True),
                        PlatformWithdrawal.status.in_(("pending", "processing")),
                    )
                )
            )
            .scalars()
            .all()
        )
        references = [withdrawal.provider_ref for withdrawal in held]

    for reference in references:
        log = logger.bind(
            module="financials",
            action="reconcile_held_withdrawal",
            provider_ref=reference[-4:],
        )
        checked += 1
        try:
            transfer = await paystack.verify_transfer(reference=reference)
        except PaystackProviderError as exc:
            log.error("transfer_verify_failed: {error}", error=str(exc))
            continue

        transfer_status = str(transfer.get("status"))
        outcome = _outcome_for(transfer_status)
        if outcome is None:
            log.info("transfer_still_held", transfer_status=transfer_status)
            continue

        async with async_session_factory() as db:
            async with db.begin():
                notices = await apply_withdrawal_transfer_outcome(
                    db,
                    reference=reference,
                    outcome=outcome,  # type: ignore[arg-type]
                    transfer=transfer,
                )
        # An empty list means the withdrawal already carried this outcome and
        # nothing changed; None means the reference was not a withdrawal.
        if not notices:
            continue
        for notice in notices:
            notice()
        reconciled += 1
        log.info("held_withdrawal_reconciled", outcome=outcome)

    return {"checked": checked, "reconciled": reconciled}


async def _settle_payout(
    *,
    payout_id: UUID,
    outcome: str,
    transfer_status: str,
    transfer: dict[str, Any],
) -> bool:
    """Record the provider's verdict on one held payout.

    Args:
        payout_id: Payout to settle.
        outcome: ``completed`` or ``failed``.
        transfer_status: The provider status that decided it, for the ledger.
        transfer: The verified transfer, which carries the fee Paystack kept.

    Returns:
        Whether the payout was changed; False if another worker got there
        first.
    """
    async with async_session_factory() as db:
        async with db.begin():
            payout = await db.get(Payout, payout_id, with_for_update=True)
            if payout is None or not payout.awaiting_otp:
                return False
            previous_status = payout.status
            payout.status = outcome
            payout.awaiting_otp = False
            if outcome == "completed":
                payout.completed_at = datetime.now(UTC)
                # The platform absorbs the transfer fee, so a payout completed
                # here has to cost what one completed by the webhook costs.
                # Origin is "backfill" because this fee was found by asking,
                # not by an event the provider delivered. The unique
                # constraint makes a late webhook a no-op rather than a
                # double charge.
                fee_minor = paystack_transfer_fee_minor(transfer)
                if fee_minor is not None and payout.provider_ref:
                    await record_provider_fee(
                        db,
                        provider="paystack",
                        source_type="payout",
                        source_id=payout.id,
                        amount_minor=fee_minor,
                        currency=payout.currency,
                        provider_ref=payout.provider_ref,
                        origin="backfill",
                    )

            await record_financial_event(
                db,
                entity_type="payout",
                entity_id=payout.id,
                event_type=f"payout_{outcome}",
                from_status=previous_status,
                to_status=outcome,
                amount=payout.amount,
                currency=payout.currency,
                provider="paystack",
                provider_ref=payout.provider_ref,
                reason_code=(
                    f"transfer_{transfer_status}" if outcome == "failed" else None
                ),
                reason_message=(
                    "Paystack ended the transfer before it was sent."
                    if outcome == "failed"
                    else None
                ),
                actor_id=payout.contributor_id,
            )
            await write_audit(
                db=db,
                actor_id=payout.contributor_id,
                action=f"payout_{outcome}",
                target_type="payout",
                target_id=payout.id,
                metadata={
                    "provider": "paystack",
                    "transfer_status": transfer_status,
                    "reconciled": True,
                },
            )
            failed_payout_id = payout.id

    if outcome == "failed":
        notify_admins_review_pending(
            domain="payout",
            target_id=failed_payout_id,
            body=(
                "A payout was ended by Paystack before it was sent, so the "
                "balance has been released and the beneficiary can request "
                "again. This happens when a transfer waits too long for a "
                "one-time code."
            ),
            link="/admin/payouts",
        )
    return True


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def reconcile_held_transfers(self: Any) -> dict[str, int]:
    """Settle payouts whose transfers the provider ended without a webhook."""
    log = logger.bind(
        module="financials",
        action="reconcile_held_transfers",
        task_id=self.request.id,
    )
    log.info("task_started")
    try:
        result = run_async(_reconcile_held_transfers())
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", **result)
    return result
