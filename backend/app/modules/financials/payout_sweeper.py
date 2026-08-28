"""Sweeper for payouts whose processing dispatch never happened.

`request_payout` books the payout row and then enqueues the processing task.
If that enqueue fails — broker down, worker restart mid-handoff — the payout
sits `pending` forever: the money is claimed against the Contributor's
balance but no transfer will ever be attempted, and nothing else notices.

This sweep re-enqueues any payout still `pending` past a grace window. The
processing worker is idempotent (a payout with a provider reference or a
non-pending status returns untouched, and provider calls carry idempotency
keys), so re-enqueueing a payout that is merely slow is always safe.

Maps to: FR-FIN-010 (payout processing reliability).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.financials.models import Payout

# Long enough that a healthy dispatch-and-process cycle always completes
# first; short enough that a Contributor is not left staring at a stuck
# payout for hours.
DISPATCH_GRACE = timedelta(minutes=15)


class PayoutSweepResult(TypedDict):
    """Counts from one stranded-payout sweep."""

    checked: int
    requeued: int


async def requeue_stranded_payouts(
    db: AsyncSession,
    *,
    enqueue: Callable[[str], None],
    now: datetime | None = None,
) -> PayoutSweepResult:
    """Re-enqueue processing for payouts stuck in `pending` past the grace.

    Args:
        db: Async session; the sweep only reads — state moves when the
            re-enqueued worker runs.
        enqueue: Dispatcher taking the payout id, normally the Celery task's
            ``delay``.
        now: Clock override for tests.

    Returns:
        Counts of stranded payouts found and successfully re-enqueued.
    """
    moment = now or datetime.now(UTC)
    cutoff = moment - DISPATCH_GRACE
    stranded = (
        (
            await db.execute(
                select(Payout)
                .where(
                    Payout.status == "pending",
                    Payout.initiated_at < cutoff,
                )
                .order_by(Payout.initiated_at)
            )
        )
        .scalars()
        .all()
    )

    result: PayoutSweepResult = {"checked": 0, "requeued": 0}
    for payout in stranded:
        result["checked"] += 1
        log = logger.bind(
            module="financials",
            action="requeue_stranded_payouts",
            payout_id=str(payout.id),
        )
        try:
            enqueue(str(payout.id))
        except Exception as exc:
            # The broker is still refusing work; the next hourly run retries.
            log.error("payout_requeue_dispatch_failed", error=str(exc))
            continue
        result["requeued"] += 1
        # WARNING, not INFO: a stranded payout means an earlier dispatch
        # failed silently, which is worth an eye even after self-healing.
        log.warning(
            "stranded_payout_requeued",
            initiated_at=payout.initiated_at.isoformat(),
        )
    return result
