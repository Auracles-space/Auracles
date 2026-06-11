"""Partner commission lifecycle services.

Handles Phase 5a commission state transitions that are shared by webhook,
scheduled clearing, analytics, and future payout slices.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.developer.models import PartnerCommission
from app.modules.financials.models import Transaction

COMMISSION_CLEARING_DELAY = timedelta(hours=48)


async def clear_partner_commissions(db: AsyncSession) -> dict[str, int]:
    """Clear mature Partner commissions and void refunded-sale commissions.

    Pending commissions become `cleared` only after the 48-hour refund window
    has elapsed and the linked purchase transaction is still completed. Pending
    commissions tied to refunded transactions are voided so they cannot be paid.
    """
    now = datetime.now(UTC)
    cutoff = now - COMMISSION_CLEARING_DELAY
    cleared_count = 0
    voided_count = 0

    rows = (
        await db.execute(
            select(PartnerCommission, Transaction)
            .join(Transaction, Transaction.id == PartnerCommission.transaction_id)
            .where(PartnerCommission.status == "pending")
            .with_for_update()
        )
    ).all()

    for commission, transaction in rows:
        if transaction.status == "refunded":
            commission.status = "voided"
            voided_count += 1
            await write_audit(
                db=db,
                actor_id=None,
                action="partner_commission_voided",
                target_type="partner_commission",
                target_id=commission.id,
                metadata={
                    "transaction_id": str(transaction.id),
                    "reason": "refund_detected_by_clearing_task",
                },
            )
            continue

        if transaction.status == "completed" and commission.created_at <= cutoff:
            commission.status = "cleared"
            commission.cleared_at = now
            cleared_count += 1
            await write_audit(
                db=db,
                actor_id=None,
                action="partner_commission_cleared",
                target_type="partner_commission",
                target_id=commission.id,
                metadata={
                    "transaction_id": str(transaction.id),
                    "cleared_after_hours": 48,
                },
            )

    return {"cleared_count": cleared_count, "voided_count": voided_count}
