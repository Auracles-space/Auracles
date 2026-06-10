"""Milestone drafting and finalization services for Project workspaces."""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.integrations import stripe
from app.integrations.stripe import StripeProviderError
from app.modules.auth.models import User
from app.modules.financials.models import Transaction
from app.modules.projects.models import Milestone, Project, Proposal
from app.modules.projects.schemas import (
    MilestoneCreateRequest,
    MilestoneFundingResponse,
    MilestonesResponse,
    MilestoneUpdateRequest,
)


def _normalise_money(amount: Decimal) -> Decimal:
    """Return a two-decimal money value for persisted funding records."""
    return amount.quantize(Decimal("0.01"))


async def _load_project_with_accepted_proposal(
    *,
    db: AsyncSession,
    project_id: UUID,
    lock_project: bool = False,
    lock_proposal: bool = False,
) -> tuple[Project, Proposal]:
    """Load a Project and its accepted Proposal, optionally under row locks."""
    project_query = select(Project).where(Project.id == project_id)
    if lock_project:
        project_query = project_query.with_for_update()
    project = await db.scalar(project_query)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    if project.accepted_proposal_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Milestones require an accepted Proposal.",
        )

    proposal_query = select(Proposal).where(
        Proposal.id == project.accepted_proposal_id,
        Proposal.project_id == project.id,
        Proposal.status == "accepted",
    )
    if lock_proposal:
        proposal_query = proposal_query.with_for_update()
    proposal = await db.scalar(proposal_query)
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Accepted Proposal is not available.",
        )
    return project, proposal


def _ensure_accepted_contributor(proposal: Proposal, contributor_id: UUID) -> None:
    """Raise unless the current user owns the accepted Proposal."""
    if proposal.contributor_id != contributor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the accepted Contributor can manage Milestones.",
        )


def _ensure_project_member(project: Project, proposal: Proposal, user_id: UUID) -> None:
    """Raise unless the current user belongs to the accepted Project workspace."""
    if user_id not in {project.operator_id, proposal.contributor_id}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Project members can view Milestones.",
        )


def _ensure_draft_plan(project: Project) -> None:
    """Raise unless the Project's Milestone plan is still editable."""
    if project.milestone_plan_status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft Milestone plans can be changed.",
        )


async def _load_pending_milestone(
    *,
    db: AsyncSession,
    project_id: UUID,
    milestone_id: UUID,
) -> Milestone:
    """Load a pending Milestone under lock or raise a typed HTTP error."""
    milestone = await db.scalar(
        select(Milestone)
        .where(Milestone.id == milestone_id, Milestone.project_id == project_id)
        .with_for_update()
    )
    if milestone is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Milestone not found.",
        )
    if milestone.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending Milestones can be changed.",
        )
    return milestone


async def _load_project_milestone_for_funding(
    *,
    db: AsyncSession,
    project_id: UUID,
    milestone_id: UUID,
    operator_id: UUID,
) -> tuple[Project, Proposal, Milestone]:
    """Load and validate the Project, accepted Proposal, and pending Milestone."""
    project, proposal = await _load_project_with_accepted_proposal(
        db=db,
        project_id=project_id,
        lock_project=True,
        lock_proposal=True,
    )
    if project.operator_id != operator_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the Project Operator can fund Milestones.",
        )
    if project.milestone_plan_status != "finalized":
        raise HTTPException(
            status_code=422,
            detail="Milestone plan must be finalized before funding.",
        )
    milestone = await _load_pending_milestone(
        db=db,
        project_id=project.id,
        milestone_id=milestone_id,
    )
    return project, proposal, milestone


async def _ensure_sequence_available(
    *,
    db: AsyncSession,
    project_id: UUID,
    sequence: int,
    exclude_milestone_id: UUID | None = None,
) -> None:
    """Reject duplicate sequence numbers before the database constraint fires."""
    query = select(Milestone.id).where(
        Milestone.project_id == project_id,
        Milestone.sequence == sequence,
    )
    if exclude_milestone_id is not None:
        query = query.where(Milestone.id != exclude_milestone_id)
    existing_id = await db.scalar(query)
    if existing_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Milestone sequence already exists for this Project.",
        )


async def _create_pending_milestone_transaction(
    *,
    db: AsyncSession,
    operator_id: UUID,
    customer_id: str,
    project_id: UUID,
    milestone_id: UUID,
) -> tuple[UUID, UUID, Decimal, str]:
    """Create the pending local transaction for a Milestone funding intent."""
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project, proposal, milestone = await _load_project_milestone_for_funding(
            db=db,
            project_id=project_id,
            milestone_id=milestone_id,
            operator_id=operator_id,
        )
        existing_transaction_id = await db.scalar(
            select(Transaction.id)
            .where(
                Transaction.ref_id == milestone.id,
                Transaction.ref_type == "project_milestone",
                Transaction.status.in_(("pending", "completed")),
            )
            .limit(1)
        )
        if existing_transaction_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Milestone already has active funding.",
            )

        operator = await db.get(User, operator_id, with_for_update=True)
        if operator is not None and operator.stripe_customer_id is None:
            operator.stripe_customer_id = customer_id

        amount = _normalise_money(milestone.budget)
        transaction = Transaction(
            payer_id=operator_id,
            payee_id=proposal.contributor_id,
            amount=amount,
            currency=milestone.currency.upper(),
            platform_commission=Decimal("0.00"),
            net_amount=amount,
            transaction_type="milestone",
            status="pending",
            provider="stripe",
            ref_id=milestone.id,
            ref_type="project_milestone",
        )
        db.add(transaction)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="milestone_funding_initiated",
            target_type="transaction",
            target_id=transaction.id,
            metadata={
                "project_id": str(project.id),
                "milestone_id": str(milestone.id),
            },
        )
        return transaction.id, proposal.contributor_id, amount, milestone.currency


async def _mark_milestone_funding_provider_ref(
    *,
    db: AsyncSession,
    operator_id: UUID,
    transaction_id: UUID,
    provider_ref: str,
    project_id: UUID,
    milestone_id: UUID,
) -> None:
    """Persist the Stripe PaymentIntent reference for a funding transaction."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        transaction = await db.get(Transaction, transaction_id)
        if transaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Milestone funding transaction not found.",
            )
        transaction.provider_ref = provider_ref
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="milestone_funding_payment_intent_created",
            target_type="transaction",
            target_id=transaction.id,
            metadata={
                "project_id": str(project_id),
                "milestone_id": str(milestone_id),
                "provider": "stripe",
                "provider_ref": provider_ref[-4:],
            },
        )


async def _mark_milestone_funding_failed(
    *,
    db: AsyncSession,
    operator_id: UUID,
    transaction_id: UUID,
    project_id: UUID,
    milestone_id: UUID,
) -> None:
    """Mark a local Milestone funding transaction failed after provider failure."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        transaction = await db.get(Transaction, transaction_id)
        if transaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Milestone funding transaction not found.",
            )
        transaction.status = "failed"
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="milestone_funding_failed",
            target_type="transaction",
            target_id=transaction.id,
            metadata={
                "project_id": str(project_id),
                "milestone_id": str(milestone_id),
                "provider": "stripe",
            },
        )


async def create_milestone(
    *,
    db: AsyncSession,
    contributor: User,
    project_id: UUID,
    payload: MilestoneCreateRequest,
) -> Milestone:
    """Create a pending Milestone while the accepted Project plan is draft."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project, proposal = await _load_project_with_accepted_proposal(
            db=db,
            project_id=project_id,
            lock_project=True,
            lock_proposal=True,
        )
        _ensure_accepted_contributor(proposal, contributor_id)
        _ensure_draft_plan(project)
        await _ensure_sequence_available(
            db=db,
            project_id=project.id,
            sequence=payload.sequence,
        )

        milestone = Milestone(
            project_id=project.id,
            sequence=payload.sequence,
            name=payload.name,
            description=payload.description,
            budget=payload.budget,
            currency=payload.currency,
            due_date=payload.due_date,
        )
        db.add(milestone)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="milestone_created",
            target_type="milestone",
            target_id=milestone.id,
            metadata={"project_id": str(project.id), "sequence": milestone.sequence},
        )
        await db.flush()
        await db.refresh(milestone)
    return milestone


async def list_milestones(
    *,
    db: AsyncSession,
    user: User,
    project_id: UUID,
) -> MilestonesResponse:
    """List Milestones for an accepted Project workspace member."""
    project, proposal = await _load_project_with_accepted_proposal(
        db=db,
        project_id=project_id,
    )
    _ensure_project_member(project, proposal, user.id)
    rows = await db.execute(
        select(Milestone)
        .where(Milestone.project_id == project.id)
        .order_by(Milestone.sequence)
    )
    return MilestonesResponse(milestones=list(rows.scalars()))


async def update_milestone(
    *,
    db: AsyncSession,
    contributor: User,
    project_id: UUID,
    milestone_id: UUID,
    payload: MilestoneUpdateRequest,
) -> Milestone:
    """Update a pending Milestone while the accepted Project plan is draft."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project, proposal = await _load_project_with_accepted_proposal(
            db=db,
            project_id=project_id,
            lock_project=True,
            lock_proposal=True,
        )
        _ensure_accepted_contributor(proposal, contributor_id)
        _ensure_draft_plan(project)
        milestone = await _load_pending_milestone(
            db=db,
            project_id=project.id,
            milestone_id=milestone_id,
        )

        updates = payload.model_dump(exclude_unset=True)
        if "sequence" in updates:
            await _ensure_sequence_available(
                db=db,
                project_id=project.id,
                sequence=updates["sequence"],
                exclude_milestone_id=milestone.id,
            )
        for key, value in updates.items():
            setattr(milestone, key, value)
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="milestone_updated",
            target_type="milestone",
            target_id=milestone.id,
            metadata={"project_id": str(project.id), "updated_fields": sorted(updates)},
        )
        await db.flush()
        await db.refresh(milestone)
    return milestone


async def delete_milestone(
    *,
    db: AsyncSession,
    contributor: User,
    project_id: UUID,
    milestone_id: UUID,
) -> None:
    """Delete a pending Milestone while the accepted Project plan is draft."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project, proposal = await _load_project_with_accepted_proposal(
            db=db,
            project_id=project_id,
            lock_project=True,
            lock_proposal=True,
        )
        _ensure_accepted_contributor(proposal, contributor_id)
        _ensure_draft_plan(project)
        milestone = await _load_pending_milestone(
            db=db,
            project_id=project.id,
            milestone_id=milestone_id,
        )
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="milestone_deleted",
            target_type="milestone",
            target_id=milestone.id,
            metadata={"project_id": str(project.id), "sequence": milestone.sequence},
        )
        await db.delete(milestone)


async def finalize_milestone_plan(
    *,
    db: AsyncSession,
    contributor: User,
    project_id: UUID,
) -> Project:
    """Finalize the draft Milestone plan when its sum matches the Proposal."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project, proposal = await _load_project_with_accepted_proposal(
            db=db,
            project_id=project_id,
            lock_project=True,
            lock_proposal=True,
        )
        _ensure_accepted_contributor(proposal, contributor_id)
        _ensure_draft_plan(project)

        total = await db.scalar(
            select(func.coalesce(func.sum(Milestone.budget), Decimal("0.00"))).where(
                Milestone.project_id == project.id
            )
        )
        if Decimal(total or "0.00") != proposal.budget:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Milestone budget total must equal the accepted Proposal "
                    "budget before finalization."
                ),
            )
        project.milestone_plan_status = "finalized"
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="milestone_plan_finalized",
            target_type="project",
            target_id=project.id,
            metadata={
                "accepted_proposal_id": str(proposal.id),
                "budget": f"{proposal.budget:.2f}",
            },
        )
        await db.flush()
        await db.refresh(project)
    return project


async def fund_milestone(
    *,
    db: AsyncSession,
    operator: User,
    project_id: UUID,
    milestone_id: UUID,
) -> MilestoneFundingResponse:
    """Create a pending Stripe PaymentIntent to fund a finalized Milestone."""
    operator_id = operator.id
    operator_email = operator.email
    operator_display_name = operator.display_name
    customer_id = operator.stripe_customer_id

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        _, _, milestone = await _load_project_milestone_for_funding(
            db=db,
            project_id=project_id,
            milestone_id=milestone_id,
            operator_id=operator_id,
        )
        amount = _normalise_money(milestone.budget)
        currency = milestone.currency.upper()

    if currency != "USD":
        raise HTTPException(
            status_code=422,
            detail="Only USD Milestone funding is supported.",
        )

    try:
        if customer_id is None:
            customer = await stripe.create_customer(
                email=operator_email,
                name=operator_display_name,
                idempotency_key=f"stripe_customer:{operator_id}",
            )
            customer_id = customer.id
    except StripeProviderError as exc:
        logger.bind(
            module="projects",
            action="fund_milestone",
            user_id=operator_id,
            project_id=project_id,
            milestone_id=milestone_id,
        ).error("stripe_customer_create_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    transaction_id, _, amount, currency = await _create_pending_milestone_transaction(
        db=db,
        operator_id=operator_id,
        customer_id=customer_id,
        project_id=project_id,
        milestone_id=milestone_id,
    )
    release_conditions = {
        "kind": "project_milestone",
        "milestone_id": str(milestone_id),
        "project_id": str(project_id),
        "approver_user_id": str(operator_id),
    }
    try:
        payment_intent = await stripe.create_payment_intent(
            customer_id=customer_id,
            amount=amount,
            currency=currency,
            metadata={
                "transaction_id": str(transaction_id),
                "kind": "escrow",
                "project_id": str(project_id),
                "milestone_id": str(milestone_id),
                "release_conditions": json.dumps(release_conditions),
            },
            idempotency_key=f"milestone_funding:{transaction_id}",
        )
    except StripeProviderError as exc:
        await _mark_milestone_funding_failed(
            db=db,
            operator_id=operator_id,
            transaction_id=transaction_id,
            project_id=project_id,
            milestone_id=milestone_id,
        )
        logger.bind(
            module="projects",
            action="fund_milestone",
            user_id=operator_id,
            project_id=project_id,
            milestone_id=milestone_id,
            transaction_id=transaction_id,
        ).error("stripe_payment_intent_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    await _mark_milestone_funding_provider_ref(
        db=db,
        operator_id=operator_id,
        transaction_id=transaction_id,
        provider_ref=payment_intent.id,
        project_id=project_id,
        milestone_id=milestone_id,
    )
    logger.bind(
        module="projects",
        action="fund_milestone",
        user_id=operator_id,
        project_id=project_id,
        milestone_id=milestone_id,
        transaction_id=transaction_id,
    ).info("milestone_funding_initiated")
    return MilestoneFundingResponse(
        transaction_id=transaction_id,
        provider="stripe",
        client_secret=payment_intent.client_secret,
    )
