"""Attestation request lifecycle service logic.

This slice creates escrow-funded Attestation requests. Matching, assignment,
reporting, release, and disputes are layered onto these records in later slices.
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.integrations import stripe
from app.integrations.stripe import StripeProviderError
from app.modules.attestation.models import Attestation, Credential
from app.modules.attestation.schemas import (
    AttestationFundingResponse,
    AttestationRequestCreateRequest,
)
from app.modules.auth.models import User
from app.modules.financials.models import PlatformConfig, Transaction
from app.modules.frameworks.models import Framework

IN_FLIGHT_ATTESTATION_STATUSES = {
    "pending_fee",
    "matching",
    "offered",
    "accepted",
    "report_submitted",
    "disputed",
    "needs_admin",
    "resolved",
}
ATTESTATION_FEE_DEFAULTS = {
    "framework": Decimal("250.00"),
    "contributor": Decimal("300.00"),
    "operator": Decimal("300.00"),
    "credential": Decimal("100.00"),
    "review_quality": Decimal("500.00"),
    "review_compliance": Decimal("1200.00"),
    "review_expert": Decimal("2500.00"),
    "review_provenance": Decimal("500.00"),
}


async def list_attestations_for_user(
    db: AsyncSession,
    *,
    user: User,
    role: str,
) -> list[Attestation]:
    """Return Attestations visible to a user in a requestor or attestor role."""
    if role == "requestor":
        predicate = Attestation.requestor_id == user.id
    elif role == "attestor":
        predicate = Attestation.attestor_id == user.id
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported Attestation list role.",
        )

    rows = await db.execute(
        select(Attestation)
        .where(predicate)
        .order_by(Attestation.created_at.desc(), Attestation.id.desc())
    )
    return list(rows.scalars().all())


def _normalise_money(amount: Decimal) -> Decimal:
    """Return a two-decimal money value for persisted payment records."""
    return amount.quantize(Decimal("0.01"))


async def request_attestation(
    db: AsyncSession,
    requestor: User,
    payload: AttestationRequestCreateRequest,
) -> AttestationFundingResponse:
    """Create a pending Attestation fee transaction and Stripe PaymentIntent."""
    requestor_id = requestor.id
    requestor_email = requestor.email
    requestor_display_name = requestor.display_name
    customer_id = requestor.stripe_customer_id

    await _validate_attestation_target(
        db=db,
        requestor_id=requestor_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
    )
    await _reject_duplicate_in_flight_request(
        db=db,
        requestor_id=requestor_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
    )
    amount = await _attestation_fee(db, payload.target_type, payload.review_type)

    try:
        if customer_id is None:
            customer = await stripe.create_customer(
                email=requestor_email,
                name=requestor_display_name,
                idempotency_key=f"stripe_customer:{requestor_id}",
            )
            customer_id = customer.id
    except StripeProviderError as exc:
        logger.bind(
            module="attestation",
            action="request_attestation",
            user_id=requestor_id,
        ).error("stripe_customer_create_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    attestation_id, transaction_id = await _create_pending_attestation_fee(
        db=db,
        requestor_id=requestor_id,
        customer_id=customer_id,
        payload=payload,
        amount=amount,
    )
    release_conditions = {
        "kind": "attestation",
        "attestation_id": str(attestation_id),
        "requestor_user_id": str(requestor_id),
    }

    try:
        payment_intent = await stripe.create_payment_intent(
            customer_id=customer_id,
            amount=amount,
            currency="USD",
            metadata={
                "transaction_id": str(transaction_id),
                "kind": "escrow",
                "attestation_id": str(attestation_id),
                "release_conditions": json.dumps(release_conditions),
            },
            idempotency_key=f"attestation_fee:{transaction_id}",
        )
    except StripeProviderError as exc:
        await _mark_attestation_fee_provider_failed(
            db=db,
            requestor_id=requestor_id,
            transaction_id=transaction_id,
            attestation_id=attestation_id,
            reason="payment_intent_create_failed",
        )
        logger.bind(
            module="attestation",
            action="request_attestation",
            user_id=requestor_id,
            transaction_id=transaction_id,
            attestation_id=attestation_id,
        ).error("stripe_payment_intent_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    await _mark_attestation_fee_provider_ref(
        db=db,
        requestor_id=requestor_id,
        transaction_id=transaction_id,
        attestation_id=attestation_id,
        provider_ref=payment_intent.id,
    )
    logger.bind(
        module="attestation",
        action="request_attestation",
        user_id=requestor_id,
        transaction_id=transaction_id,
        attestation_id=attestation_id,
    ).info("attestation_requested")
    return AttestationFundingResponse(
        id=attestation_id,
        transaction_id=transaction_id,
        provider="stripe",
        client_secret=payment_intent.client_secret,
    )


async def _validate_attestation_target(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    target_type: str,
    target_id: UUID,
) -> None:
    """Ensure the requestor owns the target they want independently attested."""
    if target_type == "credential":
        credential = await db.scalar(
            select(Credential.id).where(
                Credential.id == target_id,
                Credential.user_id == requestor_id,
            )
        )
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found.",
            )
        return

    if target_type == "framework":
        framework = await db.scalar(
            select(Framework.id).where(
                Framework.id == target_id,
                Framework.contributor_id == requestor_id,
                Framework.deleted_at.is_(None),
            )
        )
        if framework is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )
        return

    if target_type in {"contributor", "operator"} and target_id == requestor_id:
        return

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Attestation target not found.",
    )


async def _reject_duplicate_in_flight_request(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    target_type: str,
    target_id: UUID,
) -> None:
    """Reject duplicate in-flight requests by the same requestor and target."""
    existing_id = await db.scalar(
        select(Attestation.id)
        .where(
            Attestation.requestor_id == requestor_id,
            Attestation.target_type == target_type,
            Attestation.target_id == target_id,
            Attestation.status.in_(IN_FLIGHT_ATTESTATION_STATUSES),
        )
        .limit(1)
    )
    if existing_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An Attestation request for this target is already in flight.",
        )


async def _attestation_fee(
    db: AsyncSession,
    target_type: str,
    review_type: str | None,
) -> Decimal:
    """Return the configured Attestation fee for a target and review type."""
    if target_type == "framework":
        if review_type is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Framework Attestation requests require a review type.",
            )
        key = f"attestation_fee_review_{review_type}"
        default_key = f"review_{review_type}"
    else:
        key = f"attestation_fee_{target_type}"
        default_key = target_type

    configured = await db.scalar(
        select(PlatformConfig.value).where(PlatformConfig.key == key)
    )
    if configured is None:
        return ATTESTATION_FEE_DEFAULTS[default_key]
    try:
        return _normalise_money(Decimal(configured))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{key} configuration is invalid.",
        ) from exc


async def _create_pending_attestation_fee(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    customer_id: str,
    payload: AttestationRequestCreateRequest,
    amount: Decimal,
) -> tuple[UUID, UUID]:
    """Persist the Attestation and fee transaction before Stripe confirmation."""
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        user = await db.get(User, requestor_id, with_for_update=True)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )
        if user.stripe_customer_id is None:
            user.stripe_customer_id = customer_id

        attestation = Attestation(
            target_type=payload.target_type,
            target_id=payload.target_id,
            requestor_id=requestor_id,
            status="pending_fee",
            requested_specializations=payload.requested_specializations,
            requested_jurisdictions=payload.requested_jurisdictions,
            fee_amount=amount,
            currency="USD",
        )
        db.add(attestation)
        await db.flush()

        transaction = Transaction(
            payer_id=requestor_id,
            payee_id=None,
            amount=amount,
            currency="USD",
            platform_commission=Decimal("0.00"),
            net_amount=amount,
            transaction_type="attestation_fee",
            status="pending",
            provider="stripe",
            ref_id=attestation.id,
            ref_type="attestation",
        )
        db.add(transaction)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=requestor_id,
            action="attestation_requested",
            target_type="attestation",
            target_id=attestation.id,
            metadata={
                "target_type": payload.target_type,
                "target_id": str(payload.target_id),
                "transaction_id": str(transaction.id),
            },
        )
        return attestation.id, transaction.id


async def _mark_attestation_fee_provider_ref(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    transaction_id: UUID,
    attestation_id: UUID,
    provider_ref: str,
) -> None:
    """Persist Stripe PaymentIntent metadata for an Attestation fee transaction."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        transaction = await db.get(Transaction, transaction_id)
        if transaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestation fee transaction not found.",
            )
        transaction.provider_ref = provider_ref
        await write_audit(
            db=db,
            actor_id=requestor_id,
            action="attestation_fee_payment_intent_created",
            target_type="transaction",
            target_id=transaction.id,
            metadata={
                "attestation_id": str(attestation_id),
                "provider": "stripe",
                "provider_ref": provider_ref[-4:],
            },
        )


async def _mark_attestation_fee_provider_failed(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    transaction_id: UUID,
    attestation_id: UUID,
    reason: str,
) -> None:
    """Mark local Attestation funding failed after provider-side failure."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        transaction = await db.get(Transaction, transaction_id, with_for_update=True)
        attestation = await db.get(Attestation, attestation_id, with_for_update=True)
        if transaction is not None:
            transaction.status = "failed"
        if attestation is not None:
            attestation.status = "cancelled"
        await write_audit(
            db=db,
            actor_id=requestor_id,
            action="attestation_fee_failed",
            target_type="attestation",
            target_id=attestation_id,
            metadata={"transaction_id": str(transaction_id), "reason": reason},
        )
