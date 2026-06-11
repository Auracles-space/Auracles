"""Celery tasks for Partner commission payout processing.

Partner payouts use Stripe Connect transfers through the same provider adapter
as Contributor payouts, but read from `partner_payouts` and record Developer
account metadata instead of Contributor earnings metadata.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.core.security import decrypt_payout_provider_account_id
from app.integrations import stripe
from app.modules.developer.models import PartnerPayout
from app.modules.financials.models import PayoutAccount
from app.workers.async_runner import run_async
from app.workers.celery_app import app


async def _process_partner_payout_transfer(payout_id: str) -> dict[str, str]:
    """Create a provider transfer for a pending Partner payout request."""
    parsed_payout_id = UUID(payout_id)
    async with async_session_factory() as db:
        row = await db.execute(
            select(PartnerPayout, PayoutAccount)
            .join(PayoutAccount, PayoutAccount.id == PartnerPayout.payout_account_id)
            .where(PartnerPayout.id == parsed_payout_id)
        )
        result = row.one_or_none()
        if result is None:
            raise ValueError("Partner payout not found.")
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

        transfer = await stripe.create_transfer(
            amount=payout.amount,
            currency=payout.currency,
            destination_account_id=decrypt_payout_provider_account_id(
                payout_account.provider_account_id
            ),
            metadata={
                "partner_payout_id": str(payout.id),
                "developer_account_id": str(payout.developer_account_id),
            },
            idempotency_key=f"partner_payout:{payout.id}",
        )

        if db.in_transaction():
            await db.rollback()
        async with db.begin():
            payout = await db.get(PartnerPayout, parsed_payout_id)
            if payout is None:
                raise ValueError("Partner payout not found.")
            payout.status = "processing"
            payout.provider_ref = transfer.id
            await write_audit(
                db=db,
                actor_id=None,
                action="partner_payout_processing",
                target_type="partner_payout",
                target_id=payout.id,
                metadata={
                    "provider": "stripe",
                    "transfer_ref": transfer.id[-4:],
                    "amount": str(payout.amount),
                    "developer_account_id": str(payout.developer_account_id),
                },
            )
        return {
            "payout_id": str(parsed_payout_id),
            "provider_ref": transfer.id,
            "status": "processing",
        }


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def process_partner_payout(self: Any, payout_id: str) -> dict[str, str]:
    """Process a pending Partner payout by creating a Stripe transfer."""
    log = logger.bind(
        module="developer",
        action="process_partner_payout",
        task_id=self.request.id,
        payout_id=payout_id,
    )
    log.info("task_started")
    try:
        result = run_async(_process_partner_payout_transfer(payout_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
