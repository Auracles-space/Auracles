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
from app.core.database import async_session_factory
from app.integrations import paystack, stripe
from app.integrations.paystack import PaystackProviderError
from app.integrations.stripe import StripeProviderError
from app.modules.financials import commission
from app.modules.financials.ledger import record_financial_event
from app.modules.financials.models import Escrow, FinancialEvent, Transaction

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


async def _record_escrow_mismatch_durably(
    db: AsyncSession,
    *,
    existing: Escrow,
    transaction: Transaction,
) -> None:
    """Write the escrow mismatch to audit and ledger in their own commit.

    The caller's transaction is about to raise and roll back, so the record
    is committed on an independent session — a CRITICAL log line alone ages
    out of the drain, and a data-integrity event must stay queryable.
    Idempotent per conflicting transaction, because the provider redelivers
    the event that triggered it until it stops erroring.
    """
    del db  # The caller's session is mid-transaction and about to roll back.
    existing_escrow_id = existing.id
    existing_transaction_id = existing.transaction_id
    escrow_amount = _normalise_money(existing.amount)
    escrow_currency = existing.currency
    conflicting_transaction_id = transaction.id
    async with async_session_factory() as record_db, record_db.begin():
        db = record_db
        already_recorded = await db.scalar(
            select(FinancialEvent.id)
            .where(
                FinancialEvent.entity_type == "escrow",
                FinancialEvent.entity_id == existing_escrow_id,
                FinancialEvent.event_type == "escrow_mismatch",
                FinancialEvent.metadata_["conflicting_transaction_id"].astext
                == str(conflicting_transaction_id),
            )
            .limit(1)
        )
        if already_recorded is not None:
            return
        await write_audit(
            db=db,
            actor_id=None,
            action="escrow_mismatch",
            target_type="escrow",
            target_id=existing_escrow_id,
            metadata={
                "existing_transaction_id": str(existing_transaction_id),
                "conflicting_transaction_id": str(conflicting_transaction_id),
            },
        )
        await record_financial_event(
            db,
            entity_type="escrow",
            entity_id=existing_escrow_id,
            event_type="escrow_mismatch",
            amount=escrow_amount,
            currency=escrow_currency,
            reason_code="escrow_mismatch",
            metadata={
                "existing_transaction_id": str(existing_transaction_id),
                "conflicting_transaction_id": str(conflicting_transaction_id),
            },
        )


async def _ensure_matching_escrow(
    db: AsyncSession,
    existing: Escrow,
    transaction: Transaction,
) -> None:
    """Raise if an idempotent hold request conflicts with the existing escrow."""
    if (
        existing.transaction_id != transaction.id
        or _normalise_money(existing.amount) != _normalise_money(transaction.amount)
        or existing.currency.upper() != transaction.currency.upper()
    ):
        _log_escrow_mismatch(existing=existing, transaction=transaction)
        await _record_escrow_mismatch_durably(
            db,
            existing=existing,
            transaction=transaction,
        )
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
        await _ensure_matching_escrow(db, existing, transaction)
        if transaction.status != "completed":
            await commission.stamp_settling_transaction(db, transaction)
        transaction.status = "completed"
        await db.flush()
        return existing

    if transaction.status != "completed":
        # Lock the sale-time commission rate as the funds go under hold;
        # replays skip so a later rate change cannot restamp the record.
        await commission.stamp_settling_transaction(db, transaction)
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
    await record_financial_event(
        db,
        entity_type="escrow",
        entity_id=escrow.id,
        event_type="escrow_funded",
        from_status=None,
        to_status="held",
        amount=escrow.amount,
        currency=escrow.currency,
        provider=transaction.provider,
        provider_ref=transaction.provider_ref,
        actor_id=transaction.payer_id,
        metadata={"transaction_id": str(transaction.id)},
    )
    return escrow


async def _credit_project_milestone_beneficiary(
    db: AsyncSession,
    *,
    escrow: Escrow,
) -> None:
    """Stamp the released milestone transaction with its effective beneficiary."""
    if escrow.ref_type != "project_milestone":
        return

    transaction = await db.get(Transaction, escrow.transaction_id, with_for_update=True)
    if transaction is None:
        return

    # Local imports keep the financials/projects dependency one-way.
    from app.modules.projects.models import Milestone, Project, Proposal

    milestone = await db.scalar(
        select(Milestone).where(Milestone.id == escrow.ref_id).with_for_update()
    )
    if milestone is None:
        return

    project = await db.scalar(
        select(Project).where(Project.id == milestone.project_id).with_for_update()
    )
    if project is None or project.accepted_proposal_id is None:
        return

    proposal = await db.scalar(
        select(Proposal)
        .where(Proposal.id == project.accepted_proposal_id)
        .with_for_update()
    )
    if proposal is None:
        return

    if proposal.contributor_org_id is not None:
        transaction.payee_id = None
        transaction.payee_org_id = proposal.contributor_org_id
        return

    transaction.payee_id = proposal.contributor_id


async def release(
    db: AsyncSession,
    *,
    escrow_id: UUID,
    actor_id: UUID,
    reason: str,
    admin_override: bool = False,
) -> Escrow:
    """Mark held escrow funds released after workflow approval or admin override."""
    escrow = await db.get(Escrow, escrow_id, with_for_update=True)
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

    await _credit_project_milestone_beneficiary(db, escrow=escrow)
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
    await record_financial_event(
        db,
        entity_type="escrow",
        entity_id=escrow.id,
        event_type="escrow_released",
        from_status="held",
        to_status="released",
        amount=escrow.amount,
        currency=escrow.currency,
        actor_id=actor_id,
        metadata={"reason": reason.strip(), "admin_override": str(admin_override)},
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
    escrow = await db.get(Escrow, escrow_id, with_for_update=True)
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
    await record_financial_event(
        db,
        entity_type="escrow",
        entity_id=escrow.id,
        event_type="escrow_refunded",
        from_status="held",
        to_status="refunded",
        amount=escrow.amount,
        currency=escrow.currency,
        actor_id=actor_id,
        metadata={"reason": reason.strip(), "admin_override": str(admin_override)},
    )
    return escrow


async def refund_at_provider(
    db: AsyncSession,
    *,
    escrow: Escrow,
    transaction: Transaction,
    idempotency_prefix: str,
    actor_id: UUID | None = None,
) -> str:
    """Send a full escrow refund back through the rail it was funded on.

    One implementation for every caller (project disputes, attestation
    disputes, admin overrides) so the two rails cannot drift apart. Stripe
    refunds settle synchronously; Paystack accepts the refund and reports the
    outcome later, so the `refund_requested` ledger row written here is what
    lets the settlement webhook and the reconciliation sweeper close it out.

    Args:
        db: Session inside the caller's transaction — the ledger row must
            commit atomically with the local refund state the caller writes.
        escrow: The held escrow being refunded.
        transaction: Its funding transaction, already locked by the caller.
        idempotency_prefix: Caller-specific prefix keeping already-shipped
            Stripe idempotency keys stable (e.g. `escrow_dispute_refund`).
        actor_id: User driving the refund, for the ledger row.

    Returns:
        The provider's refund id.

    Raises:
        HTTPException(409): The transaction has no provider reference, or an
            unknown provider.
        HTTPException(502): The provider rejected or could not be reached.
    """
    if transaction.provider_ref is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Escrow funding transaction is missing provider metadata.",
        )

    if transaction.provider == "stripe":
        try:
            stripe_refund = await stripe.create_refund(
                payment_intent_id=transaction.provider_ref,
                amount=transaction.amount,
                currency=transaction.currency,
                idempotency_key=f"{idempotency_prefix}:{escrow.id}",
            )
        except StripeProviderError as exc:
            logger.bind(
                module="financials",
                action="refund_escrow_at_provider",
                escrow_id=escrow.id,
                transaction_id=transaction.id,
            ).error("stripe_escrow_refund_failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Payment provider is unavailable.",
            ) from exc
        refund_ref = stripe_refund.id
    elif transaction.provider == "paystack":
        try:
            paystack_refund = await paystack.refund_transaction(
                transaction_reference=transaction.provider_ref,
                amount=transaction.amount,
                currency=transaction.currency,
            )
        except PaystackProviderError as exc:
            logger.bind(
                module="financials",
                action="refund_escrow_at_provider",
                escrow_id=escrow.id,
                transaction_id=transaction.id,
            ).error("paystack_escrow_refund_failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Payment provider is unavailable.",
            ) from exc
        refund_ref = paystack_refund.id
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unsupported escrow payment provider.",
        )

    await record_financial_event(
        db,
        entity_type="transaction",
        entity_id=transaction.id,
        event_type="refund_requested",
        from_status=transaction.status,
        to_status="refunded",
        amount=transaction.amount,
        currency=transaction.currency,
        provider=transaction.provider,
        provider_ref=refund_ref,
        actor_id=actor_id,
        metadata={"escrow_id": str(escrow.id)},
    )
    return refund_ref


async def split(
    db: AsyncSession,
    *,
    escrow_id: UUID,
    actor_id: UUID,
    release_amount: Decimal,
    refund_amount: Decimal,
    reason: str,
    admin_override: bool = False,
) -> Escrow:
    """Release part of held escrow and refund the remainder through Stripe."""
    normalized_release = _normalise_money(release_amount)
    normalized_refund = _normalise_money(refund_amount)
    if normalized_release <= 0 or normalized_refund <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Split amounts must both be positive.",
        )

    escrow = await db.get(Escrow, escrow_id, with_for_update=True)
    if escrow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Escrow not found.",
        )
    if escrow.status != "held":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only held escrow can be split.",
        )
    if _normalise_money(escrow.amount) != normalized_release + normalized_refund:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Split amounts must equal the escrow amount.",
        )

    transaction = await db.get(Transaction, escrow.transaction_id, with_for_update=True)
    if transaction is None or transaction.provider_ref is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Escrow funding transaction is missing provider metadata.",
        )

    if transaction.provider == "stripe":
        try:
            refund_result_id = (
                await stripe.create_refund(
                    payment_intent_id=transaction.provider_ref,
                    amount=normalized_refund,
                    currency=transaction.currency,
                    idempotency_key=f"escrow_split_refund:{escrow_id}",
                )
            ).id
        except StripeProviderError as exc:
            logger.bind(
                module="financials",
                action="escrow_split",
                escrow_id=escrow_id,
                transaction_id=transaction.id,
            ).error("stripe_escrow_split_refund_failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Payment provider is unavailable.",
            ) from exc
    elif transaction.provider == "paystack":
        try:
            refund_result_id = (
                await paystack.refund_transaction(
                    transaction_reference=transaction.provider_ref,
                    amount=normalized_refund,
                    currency=transaction.currency,
                )
            ).id
        except PaystackProviderError as exc:
            logger.bind(
                module="financials",
                action="escrow_split",
                escrow_id=escrow_id,
                transaction_id=transaction.id,
            ).error("paystack_escrow_split_refund_failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Payment provider is unavailable.",
            ) from exc
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unsupported escrow payment provider.",
        )

    escrow.status = "released"
    escrow.released_at = datetime.now(UTC)
    escrow.released_by = actor_id
    escrow.release_conditions = {
        **(escrow.release_conditions or {}),
        "split": {
            "refund_amount": str(normalized_refund),
            "refund_ref": refund_result_id,
            "release_amount": str(normalized_release),
        },
    }
    transaction.status = "refunded"
    # The release child inherits the funding transaction's stamped rate
    # proportionally, so a split never reprices the sale-time commission.
    release_commission = (
        _normalise_money(
            transaction.platform_commission
            * (normalized_release / _normalise_money(transaction.amount))
        )
        if transaction.platform_commission > 0
        else Decimal("0.00")
    )
    db.add(
        Transaction(
            payer_id=transaction.payer_id,
            payer_org_id=transaction.payer_org_id,
            payee_id=transaction.payee_id,
            payee_org_id=transaction.payee_org_id,
            amount=normalized_release,
            currency=transaction.currency.upper(),
            platform_commission=release_commission,
            net_amount=_normalise_money(normalized_release - release_commission),
            transaction_type=transaction.transaction_type,
            status="completed",
            provider=transaction.provider,
            provider_ref=transaction.provider_ref,
            ref_id=transaction.ref_id,
            ref_type=transaction.ref_type,
        )
    )
    refund_row = Transaction(
        payer_id=transaction.payer_id,
        payer_org_id=transaction.payer_org_id,
        payee_id=None,
        amount=normalized_refund,
        currency=transaction.currency.upper(),
        platform_commission=Decimal("0.00"),
        net_amount=Decimal("0.00"),
        transaction_type="refund",
        status="refunded",
        provider=transaction.provider,
        provider_ref=refund_result_id,
        ref_id=transaction.ref_id,
        ref_type=transaction.ref_type,
    )
    db.add(refund_row)
    await db.flush()
    # Keyed on the child refund row, not the funding transaction: a split's
    # release portion already stands, so if the provider later declines the
    # refund only the child row is failed — reversing the funding transaction
    # would double-count the released money.
    await record_financial_event(
        db,
        entity_type="transaction",
        entity_id=refund_row.id,
        event_type="refund_requested",
        from_status=None,
        to_status="refunded",
        amount=normalized_refund,
        currency=transaction.currency,
        provider=transaction.provider,
        provider_ref=refund_result_id,
        actor_id=actor_id,
        metadata={"escrow_id": str(escrow.id), "split": "true"},
    )
    await write_audit(
        db=db,
        actor_id=actor_id,
        action="escrow_split",
        target_type="escrow",
        target_id=escrow.id,
        metadata={
            "reason": reason.strip(),
            "admin_override": admin_override,
            "release_amount": str(normalized_release),
            "refund_amount": str(normalized_refund),
            "refund_ref": refund_result_id,
        },
    )
    await record_financial_event(
        db,
        entity_type="escrow",
        entity_id=escrow.id,
        event_type="escrow_split",
        from_status="held",
        to_status="released",
        amount=_normalise_money(escrow.amount),
        currency=escrow.currency,
        provider=transaction.provider,
        provider_ref=refund_result_id,
        actor_id=actor_id,
        metadata={
            "release_amount": str(normalized_release),
            "refund_amount": str(normalized_refund),
        },
    )
    return escrow
