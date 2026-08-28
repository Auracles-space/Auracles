"""Attestation request lifecycle service logic.

This slice creates escrow-funded Attestation requests. Matching, assignment,
reporting, release, and disputes are layered onto these records in later slices.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.currency import platform_currency
from app.integrations import paystack, stripe
from app.integrations.payment_router import select_provider
from app.integrations.paystack import PaystackProviderError
from app.integrations.stripe import StripeProviderError
from app.modules.attestation import notifications as attestation_notifications
from app.modules.attestation.models import (
    Attestation,
    AttestationOffer,
    AttestationRubricDimension,
    AttestationRubricScore,
    Credential,
)
from app.modules.attestation.schemas import (
    AdminAttestationDetailResponse,
    AdminAttestationOfferItem,
    AttestationConsentPendingResponse,
    AttestationFundingResponse,
    AttestationRequestCreateRequest,
    AttestationRequestResponse,
    RequestorRubricItem,
)
from app.modules.auth.models import User
from app.modules.financials.models import PlatformConfig, Transaction
from app.modules.frameworks.models import Framework, FrameworkVersion
from app.modules.organizations.models import Organization, OrgMember

IN_FLIGHT_ATTESTATION_STATUSES = {
    "pending_fee",
    "pending_owner_consent",
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
        # A user sees the org attestations they staff as reviewing member plus,
        # as an org owner/admin, all of their org's attestor work.
        reviewing_member_ids = select(OrgMember.id).where(
            OrgMember.user_id == user.id
        )
        managed_org_ids = select(OrgMember.org_id).where(
            OrgMember.user_id == user.id,
            OrgMember.role.in_(("owner", "admin")),
        )
        predicate = or_(
            Attestation.reviewing_member_id.in_(reviewing_member_ids),
            Attestation.attestor_org_id.in_(managed_org_ids),
        )
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


# Statuses in which a report has been submitted and its rubric may be shown to
# the requestor. Never includes pre-submission states (accepted/in_review), so
# the requestor cannot see draft scoring before the attestor commits a report.
REPORT_RUBRIC_VISIBLE_STATUSES = {
    "report_submitted",
    "disputed",
    "resolved",
    "released",
    "refunded",
    "closed",
}


async def list_report_rubric_for_requestor(
    db: AsyncSession,
    *,
    requestor: User,
    attestation_id: UUID,
) -> list[RequestorRubricItem]:
    """Return the attestor's rubric scorecard for the report's requestor.

    The requestor funds the attestation and decides whether to accept or
    dispute the submitted report, so they see each rubric dimension's label,
    score, and comment. Visibility is gated to the requestor and to statuses
    where a report has actually been submitted.

    Args:
        db: Async database session.
        requestor: Authenticated caller; must own the attestation.
        attestation_id: Attestation whose report rubric is requested.

    Returns:
        One :class:`RequestorRubricItem` per scored dimension, in display order.

    Raises:
        HTTPException(404): The attestation does not exist, is not owned by the
            caller, or has no submitted report yet.
    """
    attestation = await db.get(Attestation, attestation_id)
    if attestation is None or attestation.requestor_id != requestor.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    if attestation.status not in REPORT_RUBRIC_VISIBLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )

    rows = await db.execute(
        select(
            AttestationRubricDimension.key,
            AttestationRubricDimension.label,
            AttestationRubricScore.score,
            AttestationRubricScore.comment,
        )
        .join(
            AttestationRubricDimension,
            AttestationRubricDimension.id == AttestationRubricScore.dimension_id,
        )
        .where(AttestationRubricScore.attestation_id == attestation_id)
        .order_by(AttestationRubricDimension.display_order)
    )
    return [
        RequestorRubricItem(
            dimension_key=key, label=label, score=score, comment=comment
        )
        for key, label, score, comment in rows.all()
    ]


async def list_admin_attestations(
    db: AsyncSession,
    *,
    status_value: str = "needs_admin",
) -> list[Attestation]:
    """Return all Attestations in a given status for admin triage.

    Defaults to the ``needs_admin`` queue — requests that auto-matching could
    not staff and that an admin must assign or refund.

    Args:
        db: Async database session.
        status_value: Attestation status to filter by.

    Returns:
        Attestations in the requested status, oldest first.
    """
    rows = await db.execute(
        select(Attestation)
        .where(Attestation.status == status_value)
        .order_by(Attestation.created_at.asc(), Attestation.id)
    )
    return list(rows.scalars().all())


async def get_admin_attestation_detail(
    db: AsyncSession,
    *,
    attestation_id: UUID,
) -> AdminAttestationDetailResponse:
    """Return an Attestation plus its offer history for admin oversight.

    Args:
        db: Async database session.
        attestation_id: Attestation to inspect.

    Returns:
        The Attestation request plus each offer made for it, with the recipient
        org's name and offer lifecycle timestamps.

    Raises:
        HTTPException(404): The Attestation does not exist.
    """
    attestation = await db.get(Attestation, attestation_id)
    if attestation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    rows = await db.execute(
        select(AttestationOffer, Organization.name)
        .outerjoin(Organization, Organization.id == AttestationOffer.org_id)
        .where(AttestationOffer.attestation_id == attestation_id)
        .order_by(AttestationOffer.offered_at.asc(), AttestationOffer.id)
    )
    offers = [
        AdminAttestationOfferItem(
            org_id=offer.org_id,
            org_name=org_name,
            status=offer.status,
            cohort_index=offer.cohort_index,
            offered_at=offer.offered_at,
            expires_at=offer.expires_at,
            responded_at=offer.responded_at,
        )
        for offer, org_name in rows.all()
    ]
    return AdminAttestationDetailResponse(
        attestation=AttestationRequestResponse.model_validate(attestation),
        offers=offers,
    )


def _normalise_money(amount: Decimal) -> Decimal:
    """Return a two-decimal money value for persisted payment records."""
    return amount.quantize(Decimal("0.01"))


async def request_attestation(
    db: AsyncSession,
    requestor: User,
    payload: AttestationRequestCreateRequest,
) -> AttestationFundingResponse | AttestationConsentPendingResponse:
    """Create an Attestation request; fund now or await owner consent."""
    requestor_id = requestor.id
    # Captured before any commit: intermediate transactions expire the ORM
    # instance, and a lazy refresh outside a greenlet context would raise.
    requestor_email = requestor.email

    initiator_is_owner = await _validate_attestation_target(
        db=db,
        requestor_id=requestor_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
    )
    if payload.target_type == "framework" and (
        payload.review_type is None or payload.brief is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Framework attestation requires a review type and brief.",
        )
    await _reject_duplicate_in_flight_request(
        db=db,
        requestor_id=requestor_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        review_type=payload.review_type,
    )
    amount = await _attestation_fee(db, payload.target_type, payload.review_type)

    if not initiator_is_owner:
        attestation_id = await _create_attestation(
            db=db,
            requestor_id=requestor_id,
            payload=payload,
            amount=amount,
            initiator_is_owner=False,
            status_value="pending_owner_consent",
        )
        owner_id = await _target_framework_owner_id(db, payload.target_id)
        if owner_id is not None:
            attestation = await db.get(Attestation, attestation_id)
            if attestation is not None:
                attestation_notifications.notify_consent_requested(
                    attestation,
                    owner_id=owner_id,
                )
        logger.bind(
            module="attestation",
            action="request_attestation",
            user_id=requestor_id,
            attestation_id=attestation_id,
        ).info("attestation_consent_requested")
        return AttestationConsentPendingResponse(
            id=attestation_id,
            status="pending_owner_consent",
        )

    provider = select_provider(
        user_country=payload.country,
        currency=platform_currency(),
    )
    customer_id = (
        await _ensure_stripe_customer(db, requestor) if provider == "stripe" else None
    )
    attestation_id = await _create_attestation(
        db=db,
        requestor_id=requestor_id,
        payload=payload,
        amount=amount,
        initiator_is_owner=True,
        status_value="pending_fee",
    )
    return await _fund_attestation(
        db=db,
        requestor_id=requestor_id,
        requestor_email=requestor_email,
        attestation_id=attestation_id,
        amount=amount,
        customer_id=customer_id,
        provider=provider,
    )


async def decide_owner_consent(
    db: AsyncSession,
    owner: User,
    *,
    attestation_id: UUID,
    decision: str,
) -> Attestation:
    """Approve or decline an operator-initiated framework attestation request.

    Args:
        db: Async database session.
        owner: Authenticated user attempting the consent decision.
        attestation_id: Attestation awaiting framework-owner consent.
        decision: Owner decision, either ``approve`` or ``decline``.

    Returns:
        The updated Attestation row.

    Raises:
        HTTPException(404): The caller is not the framework owner or the row
            does not exist.
        HTTPException(409): The attestation is not awaiting owner consent.
    """
    owner_id = owner.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        attestation = await db.get(Attestation, attestation_id, with_for_update=True)
        if attestation is None or attestation.target_type != "framework":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestation not found.",
            )
        framework_owner_id = await _target_framework_owner_id(db, attestation.target_id)
        if framework_owner_id != owner_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestation not found.",
            )
        if attestation.status != "pending_owner_consent":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attestation is not awaiting owner consent.",
            )
        if decision == "approve":
            attestation.status = "pending_fee"
            audit_action = "attestation_consent_approved"
        else:
            attestation.status = "cancelled"
            attestation.closed_at = datetime.now(UTC)
            audit_action = "attestation_consent_declined"
        await write_audit(
            db=db,
            actor_id=owner_id,
            action=audit_action,
            target_type="attestation",
            target_id=attestation.id,
            metadata={"decision": decision},
        )

    await db.refresh(attestation)
    if decision == "approve":
        attestation_notifications.notify_consent_approved(attestation)
    else:
        attestation_notifications.notify_consent_declined(attestation)
    return attestation


async def fund_attestation(
    db: AsyncSession,
    requestor: User,
    *,
    attestation_id: UUID,
    country: str | None = None,
) -> AttestationFundingResponse:
    """Fund an owner-approved operator-initiated attestation as the requestor.

    Args:
        db: Async database session.
        requestor: Authenticated user funding the attestation fee.
        attestation_id: Attestation awaiting operator payment.
        country: Optional payer billing country selecting the payment rail.

    Returns:
        Funding details including the Stripe client secret for confirmation.

    Raises:
        HTTPException(404): The attestation does not exist or is not owned by
            the requestor.
        HTTPException(409): The attestation is not awaiting payment or already
            has a fee transaction.
    """
    attestation = await db.get(Attestation, attestation_id)
    if attestation is None or attestation.requestor_id != requestor.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    if attestation.status != "pending_fee":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation is not awaiting payment.",
        )

    existing_transaction_id = await db.scalar(
        select(Transaction.id).where(
            Transaction.ref_id == attestation_id,
            Transaction.ref_type == "attestation",
        )
    )
    if existing_transaction_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation fee is already being processed.",
        )

    provider = select_provider(user_country=country, currency=platform_currency())
    customer_id = (
        await _ensure_stripe_customer(db, requestor) if provider == "stripe" else None
    )
    return await _fund_attestation(
        db=db,
        requestor_id=requestor.id,
        requestor_email=requestor.email,
        attestation_id=attestation_id,
        amount=attestation.fee_amount,
        customer_id=customer_id,
        provider=provider,
    )


async def get_attestation_fee_payment(
    db: AsyncSession,
    requestor: User,
    *,
    attestation_id: UUID,
) -> AttestationFundingResponse:
    """Return the client secret to resume payment of a pending attestation fee.

    The PaymentIntent was created when the request was funded; this re-returns
    its existing secret so the requestor can complete an unpaid fee without
    minting a duplicate intent or moving any escrow.

    Args:
        db: Async database session.
        requestor: Authenticated user resuming payment.
        attestation_id: Attestation whose fee is being paid.

    Returns:
        Funding details including the existing PaymentIntent client secret.

    Raises:
        HTTPException(404): The attestation does not exist or is not owned by
            the requestor.
        HTTPException(409): The attestation is not awaiting payment or has no
            pending fee PaymentIntent.
        HTTPException(502): The payment provider could not be reached.
    """
    attestation = await db.get(Attestation, attestation_id)
    if attestation is None or attestation.requestor_id != requestor.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    if attestation.status != "pending_fee":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation is not awaiting payment.",
        )

    transaction = await db.scalar(
        select(Transaction).where(
            Transaction.ref_id == attestation_id,
            Transaction.ref_type == "attestation",
            Transaction.status == "pending",
        )
    )
    if transaction is None or transaction.provider_ref is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No pending fee payment for this attestation.",
        )

    if transaction.provider == "paystack":
        # Paystack cannot re-serve an old hosted checkout URL, so resuming
        # re-initializes the charge; the stored reference moves to the new
        # attempt and the webhook settles whichever reference is current.
        return await _start_paystack_attestation_fee(
            db=db,
            requestor_id=requestor.id,
            requestor_email=requestor.email,
            transaction_id=transaction.id,
            attestation_id=attestation_id,
            amount=transaction.amount,
        )

    try:
        payment_intent = await stripe.retrieve_payment_intent(
            transaction.provider_ref
        )
    except StripeProviderError as exc:
        logger.bind(
            module="attestation",
            action="get_attestation_fee_payment",
            user_id=requestor.id,
            transaction_id=transaction.id,
            attestation_id=attestation_id,
        ).error("stripe_payment_intent_retrieve_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    return AttestationFundingResponse(
        id=attestation_id,
        transaction_id=transaction.id,
        provider="stripe",
        client_secret=payment_intent.client_secret,
    )


async def _ensure_stripe_customer(db: AsyncSession, requestor: User) -> str:
    """Return the requestor Stripe customer id, creating one if missing."""
    if requestor.stripe_customer_id is not None:
        return requestor.stripe_customer_id
    try:
        customer = await stripe.create_customer(
            email=requestor.email,
            name=requestor.display_name,
            idempotency_key=f"stripe_customer:{requestor.id}",
        )
    except StripeProviderError as exc:
        logger.bind(
            module="attestation",
            action="request_attestation",
            user_id=requestor.id,
        ).error("stripe_customer_create_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc
    return customer.id


async def _target_framework_owner_id(
    db: AsyncSession,
    framework_id: UUID,
) -> UUID | None:
    """Return the contributor that owns a framework, or None if absent."""
    owner_id = await db.scalar(
        select(Framework.contributor_id).where(Framework.id == framework_id)
    )
    return owner_id if isinstance(owner_id, UUID) else None


async def _current_framework_version_id(
    db: AsyncSession,
    *,
    framework_id: UUID,
) -> UUID | None:
    """Resolve the immutable version row for a framework's current version."""
    version_id = await db.scalar(
        select(FrameworkVersion.id)
        .join(Framework, Framework.id == FrameworkVersion.framework_id)
        .where(
            FrameworkVersion.framework_id == framework_id,
            FrameworkVersion.version == Framework.version,
        )
    )
    return version_id if isinstance(version_id, UUID) else None


async def _create_attestation(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    payload: AttestationRequestCreateRequest,
    amount: Decimal,
    initiator_is_owner: bool,
    status_value: str,
) -> UUID:
    """Persist an Attestation row and request audit without creating a payment."""
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        framework_version_id = None
        if payload.target_type == "framework":
            framework_version_id = await _current_framework_version_id(
                db,
                framework_id=payload.target_id,
            )
        attestation = Attestation(
            target_type=payload.target_type,
            target_id=payload.target_id,
            requestor_id=requestor_id,
            status=status_value,
            review_type=payload.review_type,
            brief=payload.brief.model_dump() if payload.brief is not None else None,
            requested_specializations=payload.requested_specializations,
            requested_jurisdictions=payload.requested_jurisdictions,
            fee_amount=amount,
            currency=platform_currency(),
            framework_version_id=framework_version_id,
        )
        db.add(attestation)
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
                "review_type": payload.review_type,
                "brief_provided": payload.brief is not None,
                "initiator_is_owner": initiator_is_owner,
            },
        )
        return attestation.id


async def _validate_attestation_target(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    target_type: str,
    target_id: UUID,
) -> bool:
    """Ensure the requestor may request attestation on the target.

    Returns:
        True when the requestor owns or is the target. False when the target is
        a published framework owned by someone else.
    """
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
        return True

    if target_type == "framework":
        framework = (
            await db.execute(
                select(Framework.contributor_id, Framework.status).where(
                    Framework.id == target_id,
                    Framework.deleted_at.is_(None),
                    # Calibration fixtures are never attestation-request targets.
                    Framework.is_calibration.is_(False),
                )
            )
        ).one_or_none()
        if framework is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )
        contributor_id, framework_status = framework
        if contributor_id == requestor_id:
            return True
        if framework_status == "published":
            return False
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )

    if target_type in {"contributor", "operator"} and target_id == requestor_id:
        return True

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
    review_type: str | None,
) -> None:
    """Reject duplicate in-flight requests by the same requestor and review type."""
    review_type_predicate = (
        Attestation.review_type.is_(None)
        if review_type is None
        else Attestation.review_type == review_type
    )
    existing_id = await db.scalar(
        select(Attestation.id)
        .where(
            Attestation.requestor_id == requestor_id,
            Attestation.target_type == target_type,
            Attestation.target_id == target_id,
            review_type_predicate,
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


async def _fund_attestation(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    requestor_email: str,
    attestation_id: UUID,
    amount: Decimal,
    customer_id: str | None,
    provider: str = "stripe",
) -> AttestationFundingResponse:
    """Create the fee transaction and provider charge for one attestation.

    Stripe bills the requestor's customer via a PaymentIntent; Paystack has no
    customer concept, so the charge is initialized with escrow metadata and
    the browser is redirected to the hosted page. The fee settles in the
    platform currency on either rail.
    """
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        user = await db.get(User, requestor_id, with_for_update=True)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )
        if customer_id is not None and user.stripe_customer_id is None:
            user.stripe_customer_id = customer_id

        transaction = Transaction(
            payer_id=requestor_id,
            payee_id=None,
            amount=amount,
            currency=platform_currency(),
            platform_commission=Decimal("0.00"),
            net_amount=amount,
            transaction_type="attestation_fee",
            status="pending",
            provider=provider,
            ref_id=attestation_id,
            ref_type="attestation",
        )
        db.add(transaction)
        await db.flush()
        transaction_id = transaction.id

    if provider == "paystack":
        return await _start_paystack_attestation_fee(
            db=db,
            requestor_id=requestor_id,
            requestor_email=requestor_email,
            transaction_id=transaction_id,
            attestation_id=attestation_id,
            amount=amount,
        )

    if customer_id is None:
        # Unreachable through the routers (the Stripe rail always resolves a
        # customer first), kept as a hard stop so a future caller cannot
        # create an unbillable PaymentIntent.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
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
            currency=platform_currency(),
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
            action="fund_attestation",
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
        action="fund_attestation",
        user_id=requestor_id,
        transaction_id=transaction_id,
        attestation_id=attestation_id,
    ).info("attestation_funded")
    return AttestationFundingResponse(
        id=attestation_id,
        transaction_id=transaction_id,
        provider="stripe",
        client_secret=payment_intent.client_secret,
    )


async def _start_paystack_attestation_fee(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    requestor_email: str,
    transaction_id: UUID,
    attestation_id: UUID,
    amount: Decimal,
) -> AttestationFundingResponse:
    """Initialize Paystack hosted checkout for a pending Attestation fee.

    Raises:
        HTTPException(502): Paystack could not initialize the charge. The
            pending transaction is marked failed first so it never strands.
    """
    release_conditions = {
        "kind": "attestation",
        "attestation_id": str(attestation_id),
        "requestor_user_id": str(requestor_id),
    }
    try:
        initialized = await paystack.initialize_transaction(
            email=requestor_email,
            amount=amount,
            currency=platform_currency(),
            metadata={
                "transaction_id": str(transaction_id),
                "kind": "escrow",
                "attestation_id": str(attestation_id),
                "release_conditions": json.dumps(release_conditions),
            },
        )
    except PaystackProviderError as exc:
        await _mark_attestation_fee_provider_failed(
            db=db,
            requestor_id=requestor_id,
            transaction_id=transaction_id,
            attestation_id=attestation_id,
            reason="paystack_initialize_failed",
        )
        logger.bind(
            module="attestation",
            action="fund_attestation",
            user_id=requestor_id,
            transaction_id=transaction_id,
            attestation_id=attestation_id,
        ).error("paystack_initialize_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    await _mark_attestation_fee_provider_ref(
        db=db,
        requestor_id=requestor_id,
        transaction_id=transaction_id,
        attestation_id=attestation_id,
        provider_ref=initialized.reference,
        provider="paystack",
    )
    logger.bind(
        module="attestation",
        action="fund_attestation",
        user_id=requestor_id,
        transaction_id=transaction_id,
        attestation_id=attestation_id,
    ).info("attestation_funded")
    return AttestationFundingResponse(
        id=attestation_id,
        transaction_id=transaction_id,
        provider="paystack",
        authorization_url=initialized.authorization_url,
    )


async def _mark_attestation_fee_provider_ref(
    db: AsyncSession,
    *,
    requestor_id: UUID,
    transaction_id: UUID,
    attestation_id: UUID,
    provider_ref: str,
    provider: str = "stripe",
) -> None:
    """Persist the provider charge reference for an Attestation fee transaction."""
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
                "provider": provider,
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
