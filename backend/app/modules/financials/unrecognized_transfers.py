"""Detection of provider transfers Auracles did not start.

The Paystack balance holds users' money, and anyone with dashboard access can
transfer out of it. A transfer webhook that matches no payout or platform
withdrawal is therefore recorded here, logged at CRITICAL, audited, and
announced to every admin at once. Recording is idempotent per transfer
reference so a later reversal updates the row without a second alert.

Maps to: platform treasury design, decision 5.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import Boolean, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.admin.notifications import notify_admins_review_pending
from app.modules.admin.treasury_schemas import (
    UnrecognizedTransferItem,
    UnrecognizedTransfersResponse,
)
from app.modules.financials.models import UnrecognizedTransfer


def _item(row: UnrecognizedTransfer) -> UnrecognizedTransferItem:
    """Map a row to its admin response."""
    return UnrecognizedTransferItem(
        id=row.id,
        provider=row.provider,
        reference=row.provider_ref,
        event_type=row.event_type,
        amount=row.amount,
        currency=row.currency,
        recipient_name=row.recipient_name,
        recipient_bank=row.recipient_bank,
        recipient_last4=row.recipient_last4,
        acknowledged_by=row.acknowledged_by,
        acknowledged_at=row.acknowledged_at,
        created_at=row.created_at,
    )


def _text(value: Any, limit: int) -> str | None:
    """Return a trimmed, length-capped string or None."""
    return value.strip()[:limit] or None if isinstance(value, str) else None


async def record_unrecognized_transfer(
    db: AsyncSession,
    *,
    provider: Literal["stripe", "paystack"],
    reference: str,
    event_type: str,
    transfer: dict[str, Any],
) -> list[Callable[[], None]]:
    """Record a transfer no Auracles payout or withdrawal accounts for.

    Args:
        db: Session inside the webhook's transaction.
        provider: Rail the transfer event arrived on.
        reference: Transfer reference from the event.
        event_type: Provider event name.
        transfer: The event's transfer object.

    Returns:
        A post-commit alert for a newly seen transfer; empty for a repeat.
    """
    amount_minor = transfer.get("amount")
    amount = (
        (Decimal(amount_minor) / 100).quantize(Decimal("0.01"))
        if isinstance(amount_minor, int)
        else None
    )
    currency = _text(transfer.get("currency"), 3)
    recipient = transfer.get("recipient")
    recipient = recipient if isinstance(recipient, dict) else {}
    details = recipient.get("details")
    details = details if isinstance(details, dict) else {}
    account_number = _text(details.get("account_number"), 64)
    values = {
        "provider": provider,
        "provider_ref": reference,
        "event_type": event_type,
        "amount": amount,
        "currency": currency.upper() if currency else None,
        "recipient_name": _text(recipient.get("name"), 255),
        "recipient_bank": _text(details.get("bank_name"), 255),
        "recipient_last4": account_number[-4:] if account_number else None,
    }
    # xmax = 0 only for a freshly inserted row, so a repeat event updates the
    # latest event type without being mistaken for a new transfer.
    statement = (
        insert(UnrecognizedTransfer)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_unrecognized_transfers_ref",
            set_={"event_type": event_type, "updated_at": func.now()},
        )
        .returning(
            UnrecognizedTransfer.id,
            literal_column("(xmax = 0)", type_=Boolean),
        )
    )
    row_id, inserted = (await db.execute(statement)).one()
    if not inserted:
        return []

    logger.bind(
        module="financials",
        action="detect_unrecognized_transfer",
        transfer_id=str(row_id),
    ).critical(
        "unrecognized_transfer_detected",
        provider=provider,
        event_type=event_type,
        amount=str(amount),
    )
    await write_audit(
        db=db,
        actor_id=None,
        action="unrecognized_transfer_detected",
        target_type="unrecognized_transfer",
        target_id=row_id,
        metadata={
            "provider": provider,
            "event_type": event_type,
            "amount": str(amount) if amount is not None else None,
            "currency": values["currency"],
            "recipient_last4": values["recipient_last4"],
        },
    )
    amount_text = f"{amount} {values['currency']}" if amount is not None else "money"
    bank = values["recipient_bank"] or "an account"
    destination = (
        f" to {bank} ****{values['recipient_last4']}"
        if values["recipient_last4"]
        else ""
    )
    body = (
        f"A {provider.title()} transfer of {amount_text}{destination} was not "
        "started by Auracles. Check who has access to the provider dashboard."
    )
    return [
        lambda: notify_admins_review_pending(
            domain="unrecognized_transfer",
            target_id=row_id,
            title="Transfer not started by Auracles",
            body=body,
            link="/admin/treasury",
        )
    ]


async def list_unrecognized_transfers(
    db: AsyncSession, *, page: int, page_size: int
) -> UnrecognizedTransfersResponse:
    """Return unrecognized transfers, unreviewed first, then newest first."""
    total = await db.scalar(select(func.count()).select_from(UnrecognizedTransfer))
    rows = (
        await db.scalars(
            select(UnrecognizedTransfer)
            .order_by(
                UnrecognizedTransfer.acknowledged_at.is_not(None),
                UnrecognizedTransfer.created_at.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return UnrecognizedTransfersResponse(
        transfers=[_item(row) for row in rows],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


async def acknowledge_unrecognized_transfer(
    db: AsyncSession, *, transfer_id: UUID, actor_id: UUID
) -> UnrecognizedTransferItem:
    """Mark an unrecognized transfer reviewed by the super-admin.

    Idempotent: a second acknowledgement returns the row unchanged.

    Raises:
        HTTPException(404): No such transfer.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        row = await db.get(UnrecognizedTransfer, transfer_id, with_for_update=True)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transfer not found.",
            )
        if row.acknowledged_at is None:
            row.acknowledged_at = datetime.now(UTC)
            row.acknowledged_by = actor_id
            await write_audit(
                db=db,
                actor_id=actor_id,
                action="unrecognized_transfer_acknowledged",
                target_type="unrecognized_transfer",
                target_id=row.id,
                metadata={"provider": row.provider},
            )
        await db.flush()
        response = _item(row)
    return response
