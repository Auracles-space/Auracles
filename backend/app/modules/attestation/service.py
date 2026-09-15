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
from app.core.config import get_settings
from app.core.currency import platform_currency
from app.integrations import paystack, stripe
from app.integrations.payment_router import select_provider
from app.integrations.paystack import PaystackProviderError
from app.integrations.stripe import StripeProviderError
from app.modules.attestation import dispute_service, rubrics
from app.modules.attestation import notifications as attestation_notifications
from app.modules.attestation.models import (
    SETTLED_ATTESTATION_STATUSES,
    Attestation,
    AttestationAnnotation,
    AttestationClarification,
    AttestationDispute,
    AttestationOffer,
    AttestationRubricDimension,
    AttestationRubricScore,
    Credential,
)
from app.modules.attestation.schemas import (
    AdminAttestationDetailResponse,
    AdminAttestationOfferItem,
    AdminAttestationReport,
    AdminClarificationItem,
    AnnotationResponse,
    AttestationConsentPendingResponse,
    AttestationDisputeSummary,
    AttestationFundingResponse,
    AttestationRequestCreateRequest,
    AttestationRequestResponse,
    RequestorRubricItem,
    ReviewTypeOption,
    ReviewTypesResponse,
)
from app.modules.auth.models import User
from app.modules.financials import escrow_service
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.modules.frameworks.models import Framework, FrameworkVersion
from app.modules.organizations.models import Organization, OrgMember
from app.shared.errors import error_detail

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
    # Naira: framework requests are billed per review type.
    "review_quality": Decimal("150000.00"),
    "review_compliance": Decimal("350000.00"),
    "review_expert": Decimal("750000.00"),
    "review_provenance": Decimal("150000.00"),
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
        reviewing_member_ids = select(OrgMember.id).where(OrgMember.user_id == user.id)
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
# Funded statuses in which no attestor has committed yet, so the requestor may
# still withdraw and take the fee back (slice 3 decision 2).
WITHDRAWABLE_FUNDED_STATUSES: frozenset[str] = frozenset(
    {"matching", "offered", "needs_admin"}
)

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
            decline_reason=offer.decline_reason,
        )
        for offer, org_name in rows.all()
    ]
    (attestation_item,) = await build_request_responses(
        db, [attestation], include_dispute=True
    )
    return AdminAttestationDetailResponse(
        attestation=attestation_item,
        offers=offers,
        report=await _admin_report(db, attestation),
    )


async def _admin_report(
    db: AsyncSession, attestation: Attestation
) -> AdminAttestationReport | None:
    """Assemble the submitted report an admin needs to rule on a dispute.

    Returns None before a report exists. The route is admin-only; it gathers
    the rubric scorecard, the reviewer's annotations and the clarification
    thread in one place so a verdict is never given without the report.
    """
    if attestation.summary is None:
        return None
    rubric_rows = await db.execute(
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
        .where(AttestationRubricScore.attestation_id == attestation.id)
        .order_by(AttestationRubricDimension.display_order)
    )
    annotations = (
        await db.execute(
            select(AttestationAnnotation)
            .where(AttestationAnnotation.attestation_id == attestation.id)
            .order_by(AttestationAnnotation.id)
        )
    ).scalars()
    clarifications = (
        await db.execute(
            select(AttestationClarification)
            .where(AttestationClarification.attestation_id == attestation.id)
            .order_by(AttestationClarification.sent_at)
        )
    ).scalars()
    return AdminAttestationReport(
        outcome=attestation.outcome,
        summary=attestation.summary,
        scope=attestation.scope,
        conditions=attestation.conditions,
        rubric=[
            RequestorRubricItem(
                dimension_key=key, label=label, score=score, comment=comment
            )
            for key, label, score, comment in rubric_rows.all()
        ],
        annotations=[AnnotationResponse.model_validate(row) for row in annotations],
        clarifications=[
            AdminClarificationItem(
                id=row.id,
                question=row.question,
                response=row.response,
                status="answered" if row.response else "open",
            )
            for row in clarifications
        ],
    )


async def build_request_responses(
    db: AsyncSession,
    attestations: list[Attestation],
    *,
    include_dispute: bool = False,
) -> list[AttestationRequestResponse]:
    """Serialise attestations with the names a reader needs to make sense of them.

    Adds the framework title for framework targets and the attestor org's
    name when one is staffed, in two batched lookups. ``include_dispute``
    attaches the latest dispute (detail view only, both parties may read it).
    """
    framework_ids = {
        row.target_id for row in attestations if row.target_type == "framework"
    }
    titles: dict[UUID, str] = {}
    if framework_ids:
        title_rows = await db.execute(
            select(Framework.id, Framework.title).where(Framework.id.in_(framework_ids))
        )
        titles = dict(title_rows.all())
    org_ids = {row.attestor_org_id for row in attestations if row.attestor_org_id}
    org_names: dict[UUID, str] = {}
    if org_ids:
        org_rows = await db.execute(
            select(Organization.id, Organization.name).where(
                Organization.id.in_(org_ids)
            )
        )
        org_names = dict(org_rows.all())
    disputes: dict[UUID, AttestationDispute] = {}
    evidence_floor: int | None = None
    if include_dispute and attestations:
        evidence_floor = await dispute_service.evidence_min_length(db)
        dispute_rows = await db.execute(
            select(AttestationDispute)
            .where(
                AttestationDispute.attestation_id.in_([row.id for row in attestations])
            )
            .order_by(AttestationDispute.created_at.desc())
        )
        for dispute in dispute_rows.scalars().all():
            disputes.setdefault(dispute.attestation_id, dispute)
    items: list[AttestationRequestResponse] = []
    for row in attestations:
        item = AttestationRequestResponse.model_validate(row)
        if row.target_type == "framework":
            item.target_title = titles.get(row.target_id)
        if row.attestor_org_id is not None:
            item.attestor_org_name = org_names.get(row.attestor_org_id)
        dispute = disputes.get(row.id)
        if dispute is not None:
            item.dispute = AttestationDisputeSummary.model_validate(dispute)
        item.dispute_evidence_min_length = evidence_floor
        items.append(item)
    return items


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
    if payload.target_type == "framework" and payload.review_type is not None:
        await _reject_review_type_attested_on_current_version(
            db=db,
            framework_id=payload.target_id,
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


async def cancel_attestation_request(
    db: AsyncSession,
    requestor: User,
    *,
    attestation_id: UUID,
) -> Attestation:
    """Withdraw the caller's own Attestation request while no attestor is committed.

    Two withdrawable stages (slice 3 decision 2):

    * ``pending_owner_consent`` — nothing has been paid; the row is cancelled.
    * ``matching`` / ``offered`` / ``needs_admin`` — the fee is held in escrow
      but no attestor has accepted. The escrow is refunded on its funding
      rail, every open offer is superseded, and each org that held one is
      told on its offers tab.

    ``pending_fee`` still refuses: cancelling there would race the payment
    webhook, which rejects any Attestation that has left ``pending_fee`` — a
    payment landing after the cancel would strand held funds. Once an
    attestor has accepted the request is committed and only accept or dispute
    remain.

    Args:
        db: Async database session.
        requestor: Authenticated user withdrawing their own request.
        attestation_id: Attestation being withdrawn.

    Returns:
        The cancelled Attestation row.

    Raises:
        HTTPException(404): The row does not exist or belongs to another
            requestor — an existence check must not leak either way.
        HTTPException(409): The fee is being paid, or an attestor has
            already accepted.
        HTTPException(502): The payment provider refused the refund.
    """
    requestor_id = requestor.id
    if db.in_transaction():
        await db.rollback()

    offer_recipients: dict[UUID, list[UUID]] = {}
    async with db.begin():
        attestation = await db.get(Attestation, attestation_id, with_for_update=True)
        if attestation is None or attestation.requestor_id != requestor_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestation not found.",
            )
        if attestation.status == "cancelled":
            # Withdrawing twice is the same outcome the caller asked for, so a
            # double-tap returns the row rather than a confusing conflict.
            return attestation
        previous_status = attestation.status
        if previous_status == "pending_fee":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "A payment may be in progress. Wait for it to settle, "
                    "then withdraw."
                ),
            )
        if previous_status not in WITHDRAWABLE_FUNDED_STATUSES and (
            previous_status != "pending_owner_consent"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "An attestor has already accepted this request, so it "
                    "can no longer be withdrawn. You can accept or dispute "
                    "the report once it is submitted."
                ),
            )
        audit_metadata: dict[str, str] = {"previous_status": previous_status}
        if previous_status in WITHDRAWABLE_FUNDED_STATUSES:
            escrow_id = await _refund_withdrawn_escrow(
                db, attestation=attestation, requestor_id=requestor_id
            )
            audit_metadata["escrow_id"] = str(escrow_id)
            offer_recipients = await _supersede_open_offers(db, attestation)
        attestation.status = "cancelled"
        attestation.closed_at = datetime.now(UTC)
        await write_audit(
            db=db,
            actor_id=requestor_id,
            action="attestation_request_withdrawn",
            target_type="attestation",
            target_id=attestation.id,
            metadata=audit_metadata,
        )

    await db.refresh(attestation)
    for org_id, recipient_ids in offer_recipients.items():
        for recipient_id in recipient_ids:
            attestation_notifications.notify_withdrawn(
                attestation, org_id=org_id, recipient_id=recipient_id
            )
    logger.bind(
        module="attestation",
        action="cancel_attestation_request",
        user_id=str(requestor_id),
        attestation_id=str(attestation_id),
    ).info("attestation_request_withdrawn")
    return attestation


async def _refund_withdrawn_escrow(
    db: AsyncSession, *, attestation: Attestation, requestor_id: UUID
) -> UUID:
    """Refund a held attestation fee back on its rail for a withdrawal.

    Locks the escrow and its funding transaction, sends the refund through
    the shared provider leg (idempotent per escrow), then marks the local
    ledger refunded. Runs inside the caller's transaction so a provider
    failure rolls the withdrawal back.
    """
    if attestation.escrow_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attestation escrow is missing.",
        )
    escrow = await db.get(Escrow, attestation.escrow_id, with_for_update=True)
    if escrow is None or escrow.status != "held":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a held attestation fee can be refunded.",
        )
    transaction = await db.get(Transaction, escrow.transaction_id, with_for_update=True)
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Escrow funding transaction not found.",
        )
    await escrow_service.refund_at_provider(
        db,
        escrow=escrow,
        transaction=transaction,
        idempotency_prefix="attestation_withdraw_refund",
        actor_id=requestor_id,
    )
    await escrow_service.refund(
        db,
        escrow_id=escrow.id,
        actor_id=requestor_id,
        reason="requestor_withdrew_request",
    )
    return escrow.id


async def _supersede_open_offers(
    db: AsyncSession, attestation: Attestation
) -> dict[UUID, list[UUID]]:
    """Close every open offer on a withdrawn request; return org → managers."""
    current_time = datetime.now(UTC)
    open_offers = (
        (
            await db.execute(
                select(AttestationOffer)
                .where(
                    AttestationOffer.attestation_id == attestation.id,
                    AttestationOffer.status == "offered",
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    recipients: dict[UUID, list[UUID]] = {}
    for offer in open_offers:
        offer.status = "superseded"
        offer.responded_at = current_time
        if offer.org_id is not None and offer.org_id not in recipients:
            rows = await db.execute(
                select(OrgMember.user_id).where(
                    OrgMember.org_id == offer.org_id,
                    OrgMember.role.in_(("owner", "admin")),
                )
            )
            recipients[offer.org_id] = list(rows.scalars().all())
    return recipients


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
        payment_intent = await stripe.retrieve_payment_intent(transaction.provider_ref)
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


async def _reject_review_type_attested_on_current_version(
    db: AsyncSession,
    *,
    framework_id: UUID,
    review_type: str,
) -> None:
    """Refuse a review type already settled for the framework's current version.

    Human decision 2026-09-15: a review type is attested once per framework
    version, whoever asked and whatever the outcome, so a requestor cannot shop
    for a different attestor on unchanged content. A newer version reopens it.

    Raises:
        HTTPException(409): ``review_type_already_attested``.
    """
    version_id = await _current_framework_version_id(db, framework_id=framework_id)
    if version_id is None:
        return
    settled_id = await db.scalar(
        select(Attestation.id)
        .where(
            Attestation.target_type == "framework",
            Attestation.target_id == framework_id,
            Attestation.review_type == review_type,
            Attestation.framework_version_id == version_id,
            Attestation.status.in_(SETTLED_ATTESTATION_STATUSES),
        )
        .limit(1)
    )
    if settled_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(
                "review_type_already_attested",
                "This review type is already attested for the current version. "
                "Publish a new version to request it again.",
            ),
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


async def list_review_types(db: AsyncSession) -> ReviewTypesResponse:
    """Return every framework review type with its summary and live fee.

    Fees are read from platform config on each call, so an admin repricing a
    review type is what the next requestor sees.

    Args:
        db: Async database session.

    Returns:
        The review types in request-form order.
    """
    currency = platform_currency()
    return ReviewTypesResponse(
        review_types=[
            ReviewTypeOption(
                key=key,
                label=label,
                description=description,
                fee_amount=await _attestation_fee(db, "framework", key),
                currency=currency,
            )
            for key, label, description in rubrics.REVIEW_TYPE_OPTIONS
        ]
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

    Sends Paystack a `callback_url` back to the Attestation. Without one
    Paystack leaves the payer on its own success page, where the requestor
    sees no confirmation from us and can pay a second time; the escrow itself
    still settles from the webhook, so the symptom is a stranded user rather
    than lost money.

    Raises:
        HTTPException(502): Paystack could not initialize the charge. The
            pending transaction is marked failed first so it never strands.
    """
    release_conditions = {
        "kind": "attestation",
        "attestation_id": str(attestation_id),
        "requestor_user_id": str(requestor_id),
    }
    callback_url = (
        f"{get_settings().frontend_base_url}/attestations/{attestation_id}?funded=1"
    )
    try:
        initialized = await paystack.initialize_transaction(
            callback_url=callback_url,
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
