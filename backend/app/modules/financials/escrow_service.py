"""Escrow lifecycle service for held project and attestation funds."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.financials.models import Escrow, Transaction

ESCROW_REF_TYPES = {"project_milestone", "attestation"}
ESCROW_TRANSACTION_TYPES = {"milestone", "attestation_fee"}


def _normalise_money(amount: Decimal) -> Decimal:
    """Return a two-decimal money value for escrow comparisons."""
    return amount.quantize(Decimal("0.01"))


def _log_escrow_mismatch(
    *,
    existing: Escrow,
    transaction: Transaction,
) -> None:
    """Emit a critical log when one escrow ref maps to conflicting money data."""
    logger.bind(
        module="financials",
        action="escrow_mismatch",
        escrow_id=existing.id,
        transaction_id=transaction.id,
        existing_transaction_id=existing.transaction_id,
        ref_id=existing.ref_id,
        ref_type=existing.ref_type,
    ).critical("escrow_mismatch")


def _ensure_escrow_transaction(transaction: Transaction) -> None:
    """Validate that a transaction can fund an escrow ledger row."""
    if transaction.transaction_type not in ESCROW_TRANSACTION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transaction type cannot fund escrow.",
        )
    if transaction.status in {"failed", "refunded"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transaction cannot fund escrow in its current state.",
        )
    if transaction.ref_id is None or transaction.ref_type not in ESCROW_REF_TYPES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Escrow transaction is missing a supported reference.",
        )


def _ensure_matching_escrow(existing: Escrow, transaction: Transaction) -> None:
    """Raise if an idempotent hold request conflicts with the existing escrow."""
    if (
        existing.transaction_id != transaction.id
        or _normalise_money(existing.amount) != _normalise_money(transaction.amount)
        or existing.currency.upper() != transaction.currency.upper()
    ):
        _log_escrow_mismatch(existing=existing, transaction=transaction)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Escrow reference already exists with different funding data.",
        )


async def hold(
    db: AsyncSession,
    *,
    transaction_id: UUID,
    release_conditions: dict[str, Any] | None = None,
) -> Escrow:
    """Create or return the held escrow row for a completed funding payment."""
    transaction = await db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Escrow funding transaction not found.",
        )
    _ensure_escrow_transaction(transaction)
    assert transaction.ref_id is not None
    assert transaction.ref_type is not None

    existing = await db.scalar(
        select(Escrow).where(
            Escrow.ref_id == transaction.ref_id,
            Escrow.ref_type == transaction.ref_type,
        )
    )
    if existing is not None:
        _ensure_matching_escrow(existing, transaction)
        transaction.status = "completed"
        return existing

    transaction.status = "completed"
    escrow = Escrow(
        ref_id=transaction.ref_id,
        ref_type=transaction.ref_type,
        amount=_normalise_money(transaction.amount),
        currency=transaction.currency.upper(),
        status="held",
        release_conditions=release_conditions or {},
        transaction_id=transaction.id,
    )
    db.add(escrow)
    await db.flush()
    await write_audit(
        db=db,
        actor_id=transaction.payer_id,
        action="escrow_funded",
        target_type="escrow",
        target_id=escrow.id,
        metadata={
            "transaction_id": str(transaction.id),
            "ref_id": str(escrow.ref_id),
            "ref_type": escrow.ref_type,
        },
    )
    return escrow


async def release(
    db: AsyncSession,
    *,
    escrow_id: UUID,
    actor_id: UUID,
    reason: str,
    admin_override: bool = False,
) -> Escrow:
    """Mark held escrow funds released after workflow approval or admin override."""
    escrow = await db.get(Escrow, escrow_id)
    if escrow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Escrow not found.",
        )
    if escrow.status == "released":
        return escrow
    if escrow.status == "refunded":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Refunded escrow cannot be released.",
        )

    escrow.status = "released"
    escrow.released_at = datetime.now(UTC)
    escrow.released_by = actor_id
    await write_audit(
        db=db,
        actor_id=actor_id,
        action="escrow_released",
        target_type="escrow",
        target_id=escrow.id,
        metadata={"reason": reason.strip(), "admin_override": admin_override},
    )
    return escrow


async def refund(
    db: AsyncSession,
    *,
    escrow_id: UUID,
    actor_id: UUID,
    reason: str,
    admin_override: bool = False,
) -> Escrow:
    """Mark held escrow funds refunded after dispute resolution or cancellation."""
    escrow = await db.get(Escrow, escrow_id)
    if escrow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Escrow not found.",
        )
    if escrow.status == "refunded":
        return escrow
    if escrow.status == "released":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Released escrow cannot be refunded.",
        )

    escrow.status = "refunded"
    transaction = await db.get(Transaction, escrow.transaction_id)
    if transaction is not None:
        transaction.status = "refunded"
    await write_audit(
        db=db,
        actor_id=actor_id,
        action="escrow_refunded",
        target_type="escrow",
        target_id=escrow.id,
        metadata={"reason": reason.strip(), "admin_override": admin_override},
    )
    return escrow
