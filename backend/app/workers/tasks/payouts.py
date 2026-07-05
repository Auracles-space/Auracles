"""Celery tasks for Contributor payout processing."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.core.security import decrypt_payout_provider_account_id
from app.integrations import stripe
from app.modules.financials.models import Payout, PayoutAccount
from app.workers.async_runner import run_async
from app.workers.celery_app import app


async def _process_payout_transfer(payout_id: str) -> dict[str, str]:
    """Create a provider transfer for a pending payout request."""
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
        transfer = await stripe.create_transfer(
            amount=payout.net_amount,
            currency=payout.currency,
            destination_account_id=decrypt_payout_provider_account_id(
                payout_account.provider_account_id
            ),
            metadata={
                "payout_id": str(payout.id),
                **beneficiary_meta,
            },
            idempotency_key=f"payout:{payout.id}",
        )

        if db.in_transaction():
            await db.rollback()
        async with db.begin():
            payout = await db.get(Payout, parsed_payout_id)
            if payout is None:
                raise ValueError("Payout not found.")
            payout.status = "processing"
            payout.provider_ref = transfer.id
            await write_audit(
                db=db,
                actor_id=payout.contributor_id,
                action="payout_processing",
                target_type="payout",
                target_id=payout.id,
                metadata={
                    "provider": "stripe",
                    "transfer_ref": transfer.id[-4:],
                    "net_amount": str(payout.net_amount),
                },
            )
        return {
            "payout_id": str(parsed_payout_id),
            "provider_ref": transfer.id,
            "status": "processing",
        }


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def process_payout(self: Any, payout_id: str) -> dict[str, str]:
    """Process a pending payout by creating a Stripe Connect transfer."""
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
