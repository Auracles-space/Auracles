"""Milestone drafting and finalization services for Project workspaces."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.currency import platform_currency
from app.integrations import paystack, s3, stripe
from app.integrations.payment_router import select_provider
from app.integrations.paystack import PaystackProviderError
from app.integrations.stripe import StripeProviderError
from app.modules.auth.models import User
from app.modules.financials import escrow_service
from app.modules.financials.models import Escrow, Transaction
from app.modules.projects import notifications as project_notifications
from app.modules.projects.models import (
    Deliverable,
    Dispute,
    Milestone,
    Project,
    Proposal,
)
from app.modules.projects.operator_ownership import (
    resolve_operator_recipient_user_ids,
    user_is_project_member,
)
from app.modules.projects.schemas import (
    DeliverableDownloadResponse,
    DeliverableFileDownload,
    DeliverableResponse,
    DeliverableRevisionRequest,
    DeliverablesResponse,
    DeliverableSubmitRequest,
    FrameworkPrefillResponse,
    MilestoneCreateRequest,
    MilestoneFundingResponse,
    MilestonesResponse,
    MilestoneUpdateRequest,
)
from app.modules.projects.workspace import workspace_contributor_user_id
from app.modules.workspace.models import WorkspaceMessage, WorkspaceUploadSession
from app.workers.tasks.deliverable_scan import scan_deliverable_upload


def _normalise_money(amount: Decimal) -> Decimal:
    """Return a two-decimal money value for persisted funding records."""
    return amount.quantize(Decimal("0.01"))


def _workspace_system_message(
    *,
    project_id: UUID,
    system_event: str,
    payload: dict[str, Any],
) -> WorkspaceMessage:
    """Build a workspace system message for Project collaboration history."""
    return WorkspaceMessage(
        project_id=project_id,
        sender_id=None,
        system_event=system_event,
        system_payload=payload,
    )


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


async def _ensure_accepted_contributor(
    db: AsyncSession, proposal: Proposal, contributor_id: UUID
) -> None:
    """Raise unless the current user represents the accepted Proposal.

    Admits the individual Contributor for user-owned Proposals and the staffed
    delivering member for organization-owned Proposals.
    """
    workspace_user_id = await workspace_contributor_user_id(db, proposal=proposal)
    if workspace_user_id is None or workspace_user_id != contributor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the accepted Contributor can manage Milestones.",
        )


async def _resolve_workspace_contributor_seller(
    db: AsyncSession,
    *,
    proposal: Proposal,
    contributor_id: UUID,
) -> tuple[UUID | None, UUID | None]:
    """Authorize a workspace contributor and return the Deliverable seller stamp."""
    await _ensure_accepted_contributor(db, proposal, contributor_id)
    if proposal.contributor_org_id is None:
        return proposal.contributor_id, None
    return None, proposal.contributor_org_id


async def _proposal_workspace_user_id(
    db: AsyncSession,
    *,
    proposal: Proposal,
) -> UUID:
    """Resolve the user currently representing the accepted Proposal."""
    user_id = await workspace_contributor_user_id(db, proposal=proposal)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Accepted Proposal is missing its staffed delivery member.",
        )
    return user_id


async def _ensure_project_member(
    db: AsyncSession, project: Project, proposal: Proposal, user_id: UUID
) -> None:
    """Raise unless the current user belongs to the accepted Project workspace.

    Admits the accepted-Contributor side and the Operator side: the individual
    Operator, or any owner/admin of the operating organization for an
    org-operated Project.
    """
    if not await user_is_project_member(
        db, project=project, proposal=proposal, user_id=user_id
    ):
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


async def _load_org_project_milestone_for_funding(
    *,
    db: AsyncSession,
    project_id: UUID,
    milestone_id: UUID,
    org_id: UUID,
) -> tuple[Project, Proposal, Milestone]:
    """Load and validate an org-operated Project's fundable Milestone.

    Sibling of :func:`_load_project_milestone_for_funding` for the org Operator
    branch: the Project is matched on ``operator_org_id`` and a mismatch surfaces
    as 404 (cross-org access is indistinguishable from a missing resource).
    """
    project, proposal = await _load_project_with_accepted_proposal(
        db=db,
        project_id=project_id,
        lock_project=True,
        lock_proposal=True,
    )
    if project.operator_org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
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


async def _load_project_milestone_for_workspace_action(
    *,
    db: AsyncSession,
    project_id: UUID,
    milestone_id: UUID,
    lock_project: bool = True,
    lock_milestone: bool = True,
) -> tuple[Project, Proposal, Milestone]:
    """Load accepted Project workspace rows for deliverable state changes."""
    project, proposal = await _load_project_with_accepted_proposal(
        db=db,
        project_id=project_id,
        lock_project=lock_project,
        lock_proposal=True,
    )
    milestone_query = select(Milestone).where(
        Milestone.id == milestone_id,
        Milestone.project_id == project.id,
    )
    if lock_milestone:
        milestone_query = milestone_query.with_for_update()
    milestone = await db.scalar(milestone_query)
    if milestone is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Milestone not found.",
        )
    return project, proposal, milestone


async def _load_deliverable_for_update(
    *,
    db: AsyncSession,
    milestone_id: UUID,
    deliverable_id: UUID,
) -> Deliverable:
    """Load a Deliverable under lock or raise a typed HTTP error."""
    deliverable = await db.scalar(
        select(Deliverable)
        .where(
            Deliverable.id == deliverable_id,
            Deliverable.milestone_id == milestone_id,
        )
        .with_for_update()
    )
    if deliverable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deliverable not found.",
        )
    return deliverable


DELIVERABLE_DOWNLOAD_TTL_SECONDS = 900


async def list_deliverables(
    *,
    db: AsyncSession,
    user: User,
    project_id: UUID,
    milestone_id: UUID,
) -> DeliverablesResponse:
    """List Deliverables for a Milestone, newest first, for a Project member."""
    project, proposal, milestone = await _load_project_milestone_for_workspace_action(
        db=db,
        project_id=project_id,
        milestone_id=milestone_id,
        lock_project=False,
        lock_milestone=False,
    )
    await _ensure_project_member(db, project, proposal, user.id)
    rows = await db.execute(
        select(Deliverable)
        .where(Deliverable.milestone_id == milestone.id)
        .order_by(Deliverable.submitted_at.desc())
    )
    return DeliverablesResponse(
        deliverables=[
            DeliverableResponse.model_validate(deliverable)
            for deliverable in rows.scalars()
        ]
    )


async def create_deliverable_download(
    *,
    db: AsyncSession,
    user: User,
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
) -> DeliverableDownloadResponse:
    """Issue presigned download URLs for a Deliverable's files.

    Restricted to Project members, and only for a Deliverable whose files have
    passed the virus scan (``scan_status == 'visible'``). Each request is audited
    and the URLs force attachment download to avoid inline rendering.
    """
    user_id = user.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        (
            project,
            proposal,
            milestone,
        ) = await _load_project_milestone_for_workspace_action(
            db=db,
            project_id=project_id,
            milestone_id=milestone_id,
            lock_project=False,
            lock_milestone=False,
        )
        await _ensure_project_member(db, project, proposal, user_id)
        deliverable = await db.scalar(
            select(Deliverable).where(
                Deliverable.id == deliverable_id,
                Deliverable.milestone_id == milestone.id,
            )
        )
        if deliverable is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deliverable not found.",
            )
        if deliverable.scan_status != "visible":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Deliverable files are still being scanned or were quarantined."
                ),
            )
        settings = get_settings()
        files = []
        for file_key in deliverable.file_keys:
            file_name = file_key.rsplit("/", 1)[-1]
            url = s3.storage.presigned_get(
                settings.s3_artifacts_bucket,
                file_key,
                DELIVERABLE_DOWNLOAD_TTL_SECONDS,
                download_name=file_name,
            )
            files.append(
                DeliverableFileDownload(file_key=file_key, file_name=file_name, url=url)
            )
        await write_audit(
            db=db,
            actor_id=user_id,
            action="deliverable_downloaded",
            target_type="deliverable",
            target_id=deliverable.id,
            metadata={
                "milestone_id": str(milestone.id),
                "file_count": len(files),
            },
        )
    return DeliverableDownloadResponse(files=files)


async def _maybe_mark_project_delivered(
    db: AsyncSession,
    *,
    project: Project,
    now: datetime,
) -> None:
    """Mark Project delivered when every Milestone is terminally complete."""
    active_count = await db.scalar(
        select(func.count(Milestone.id)).where(
            Milestone.project_id == project.id,
            Milestone.status.notin_(("approved", "auto_approved", "cancelled")),
        )
    )
    total_count = await db.scalar(
        select(func.count(Milestone.id)).where(Milestone.project_id == project.id)
    )
    if int(total_count or 0) > 0 and int(active_count or 0) == 0:
        project.status = "delivered"
        project.delivered_at = project.delivered_at or now


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
    customer_id: str | None,
    project_id: UUID,
    milestone_id: UUID,
    provider: str = "stripe",
) -> tuple[UUID, UUID | None, Decimal, str, str]:
    """Create the pending local transaction for a Milestone funding attempt.

    On resume of an abandoned attempt the stored transaction's provider wins
    over the requested one: switching rails mid-funding would strand a
    provider-side charge the webhook could still settle.
    """
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project, proposal, milestone = await _load_project_milestone_for_funding(
            db=db,
            project_id=project_id,
            milestone_id=milestone_id,
            operator_id=operator_id,
        )
        existing = await db.scalar(
            select(Transaction)
            .where(
                Transaction.ref_id == milestone.id,
                Transaction.ref_type == "project_milestone",
                Transaction.status.in_(("pending", "completed")),
            )
            .limit(1)
        )
        if existing is not None:
            if existing.status == "completed":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Milestone is already funded.",
                )
            # A pending attempt is resumable: reusing its id keeps the Stripe
            # idempotency key stable (same intent and client secret back), and
            # on Paystack lets a fresh reference replace the abandoned one.
            return (
                existing.id,
                proposal.contributor_id,
                _normalise_money(milestone.budget),
                milestone.currency,
                existing.provider or "stripe",
            )

        operator = await db.get(User, operator_id, with_for_update=True)
        if (
            operator is not None
            and customer_id is not None
            and operator.stripe_customer_id is None
        ):
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
            provider=provider,
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
        return (
            transaction.id,
            proposal.contributor_id,
            amount,
            milestone.currency,
            provider,
        )


async def _create_pending_org_milestone_transaction(
    *,
    db: AsyncSession,
    org_id: UUID,
    actor_id: UUID,
    project_id: UUID,
    milestone_id: UUID,
    provider: str = "stripe",
) -> tuple[UUID, Decimal, str, str]:
    """Create the pending org-payer transaction for a Milestone funding intent.

    Sibling of :func:`_create_pending_milestone_transaction` for the org
    Operator branch: stamps ``payer_org_id`` with ``payer_id`` NULL (mirroring
    the org purchase pay-in) and never lazily creates or stamps a user Stripe
    customer. Resolves the Deliverable-side beneficiary from the accepted
    Proposal so an org Contributor is credited via ``payee_org_id``.

    Returns:
        The transaction id, normalized amount, and currency. A resumable pending
        transaction from an abandoned attempt is returned instead of a new one.
    """
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project, proposal, milestone = (
            await _load_org_project_milestone_for_funding(
                db=db,
                project_id=project_id,
                milestone_id=milestone_id,
                org_id=org_id,
            )
        )
        existing = await db.scalar(
            select(Transaction)
            .where(
                Transaction.ref_id == milestone.id,
                Transaction.ref_type == "project_milestone",
                Transaction.status.in_(("pending", "completed")),
            )
            .limit(1)
        )
        if existing is not None:
            if existing.status == "completed":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Milestone is already funded.",
                )
            return (
                existing.id,
                _normalise_money(milestone.budget),
                milestone.currency,
                existing.provider or "stripe",
            )

        amount = _normalise_money(milestone.budget)
        transaction = Transaction(
            payer_id=None,
            payer_org_id=org_id,
            payee_id=proposal.contributor_id,
            payee_org_id=proposal.contributor_org_id,
            amount=amount,
            currency=milestone.currency.upper(),
            platform_commission=Decimal("0.00"),
            net_amount=amount,
            transaction_type="milestone",
            status="pending",
            provider=provider,
            ref_id=milestone.id,
            ref_type="project_milestone",
        )
        db.add(transaction)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="milestone_funding_initiated",
            target_type="transaction",
            target_id=transaction.id,
            metadata={
                "project_id": str(project.id),
                "milestone_id": str(milestone.id),
                "payer_org_id": str(org_id),
            },
        )
        return transaction.id, amount, milestone.currency, provider


async def _mark_milestone_funding_provider_ref(
    *,
    db: AsyncSession,
    operator_id: UUID,
    transaction_id: UUID,
    provider_ref: str,
    project_id: UUID,
    milestone_id: UUID,
    provider: str = "stripe",
) -> None:
    """Persist the provider charge reference for a funding transaction."""
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
                "provider": provider,
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
    provider: str = "stripe",
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
                "provider": provider,
            },
        )


async def _start_paystack_milestone_funding(
    *,
    db: AsyncSession,
    operator_id: UUID,
    operator_email: str,
    transaction_id: UUID,
    project_id: UUID,
    milestone_id: UUID,
    amount: Decimal,
    currency: str,
) -> MilestoneFundingResponse:
    """Initialize Paystack hosted checkout for a pending Milestone funding.

    Paystack has no PaymentIntent equivalent: the charge is initialized with
    escrow metadata the webhook needs to hold funds, and the browser is sent
    to Paystack's own page. Mirrors `_start_paystack_purchase` in financials.

    Raises:
        HTTPException(502): Paystack could not initialize the charge. The
            pending transaction is marked failed first so it never strands.
    """
    release_conditions = {
        "kind": "project_milestone",
        "milestone_id": str(milestone_id),
        "project_id": str(project_id),
        "approver_user_id": str(operator_id),
    }
    try:
        initialized = await paystack.initialize_transaction(
            email=operator_email,
            amount=amount,
            currency=currency,
            metadata={
                "transaction_id": str(transaction_id),
                "kind": "escrow",
                "project_id": str(project_id),
                "milestone_id": str(milestone_id),
                "release_conditions": json.dumps(release_conditions),
            },
        )
    except PaystackProviderError as exc:
        await _mark_milestone_funding_failed(
            db=db,
            operator_id=operator_id,
            transaction_id=transaction_id,
            project_id=project_id,
            milestone_id=milestone_id,
            provider="paystack",
        )
        logger.bind(
            module="projects",
            action="fund_milestone",
            user_id=operator_id,
            project_id=project_id,
            milestone_id=milestone_id,
            transaction_id=transaction_id,
        ).error("paystack_initialize_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    await _mark_milestone_funding_provider_ref(
        db=db,
        operator_id=operator_id,
        transaction_id=transaction_id,
        provider_ref=initialized.reference,
        project_id=project_id,
        milestone_id=milestone_id,
        provider="paystack",
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
        provider="paystack",
        authorization_url=initialized.authorization_url,
    )


async def _ensure_within_proposal_budget(
    *,
    db: AsyncSession,
    project_id: UUID,
    proposal: Proposal,
    new_budget: Decimal,
    exclude_milestone_id: UUID | None = None,
) -> None:
    """Reject a Milestone budget that pushes the plan total over the Proposal.

    Upper-bound guard: the running ``SUM(milestone budgets)`` may not exceed the
    accepted Proposal budget (the agreed value). Under-sum is still allowed while
    drafting; the strict ``SUM == proposal.budget`` invariant remains enforced at
    finalize. ``exclude_milestone_id`` omits the Milestone being edited so an
    in-place budget change is measured against the other Milestones only.

    Args:
        db: Async session.
        project_id: Project whose Milestone budgets are summed.
        proposal: Accepted Proposal supplying the agreed budget ceiling.
        new_budget: Budget of the Milestone being created or updated.
        exclude_milestone_id: Milestone to exclude from the existing total.

    Raises:
        HTTPException(422): If the resulting total would exceed the Proposal budget.
    """
    query = select(func.coalesce(func.sum(Milestone.budget), Decimal("0.00"))).where(
        Milestone.project_id == project_id
    )
    if exclude_milestone_id is not None:
        query = query.where(Milestone.id != exclude_milestone_id)
    existing_total = Decimal(await db.scalar(query) or "0.00")
    if existing_total + new_budget > proposal.budget:
        raise HTTPException(
            status_code=422,
            detail=(
                "Milestone budget total may not exceed the accepted Proposal budget."
            ),
        )


def _ensure_due_date_within_deadline(
    *,
    due_date: date | None,
    project: Project,
) -> None:
    """Reject a Milestone due date outside the valid scheduling window.

    A due date is optional. When supplied it must be today-or-later and, when the
    Project carries a deadline, on or before it — a Milestone may not be scheduled
    to finish after the Project it belongs to.

    Args:
        due_date: Proposed Milestone due date, or ``None`` to leave it unset.
        project: Parent Project supplying the optional deadline ceiling.

    Raises:
        HTTPException(422): If the due date is in the past or after the deadline.
    """
    if due_date is None:
        return
    if due_date < date.today():
        raise HTTPException(
            status_code=422,
            detail="Milestone due date cannot be in the past.",
        )
    if project.deadline is not None and due_date > project.deadline:
        raise HTTPException(
            status_code=422,
            detail="Milestone due date must fall on or before the project deadline.",
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
        await _ensure_accepted_contributor(db, proposal, contributor_id)
        _ensure_draft_plan(project)
        await _ensure_sequence_available(
            db=db,
            project_id=project.id,
            sequence=payload.sequence,
        )
        await _ensure_within_proposal_budget(
            db=db,
            project_id=project.id,
            proposal=proposal,
            new_budget=payload.budget,
        )
        _ensure_due_date_within_deadline(due_date=payload.due_date, project=project)

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
    await _ensure_project_member(db, project, proposal, user.id)
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
        await _ensure_accepted_contributor(db, proposal, contributor_id)
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
        if "budget" in updates:
            await _ensure_within_proposal_budget(
                db=db,
                project_id=project.id,
                proposal=proposal,
                new_budget=updates["budget"],
                exclude_milestone_id=milestone.id,
            )
        if "due_date" in updates:
            _ensure_due_date_within_deadline(
                due_date=updates["due_date"], project=project
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
        await _ensure_accepted_contributor(db, proposal, contributor_id)
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
        await _ensure_accepted_contributor(db, proposal, contributor_id)
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
        db.add(
            _workspace_system_message(
                project_id=project.id,
                system_event="milestone_plan_finalized",
                payload={"finalized_by": str(contributor_id)},
            )
        )
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
        # Resolve the Operator-side recipients inside the transaction: the
        # individual Operator, or every owner/admin of the operating org.
        operator_recipient_ids = await resolve_operator_recipient_user_ids(
            db, project=project
        )
        await db.flush()
        await db.refresh(project)
    # Notify after commit so recipients only hear about a durably finalized plan
    # and know escrow funding is the next step.
    for operator_id in operator_recipient_ids:
        project_notifications.notify_milestone_plan_finalized(
            operator_id=operator_id,
            project_id=project_id,
            operator_org_id=project.operator_org_id,
        )
    return project


async def reopen_milestone_plan(
    *,
    db: AsyncSession,
    user: User,
    project_id: UUID,
) -> Project:
    """Reopen a finalized Milestone plan to draft while no Milestone is funded.

    Either Project member (the Operator or the accepted Contributor) may reopen,
    so the breakdown can be renegotiated after finalization — e.g. the Operator
    asks for a different split of the same agreed budget. Refused once any
    Milestone has moved beyond ``pending`` (funding has begun), so reopening can
    never disturb held Escrow. The strict ``SUM == proposal.budget`` invariant is
    re-checked when the Contributor finalizes again.

    Args:
        db: Async session.
        user: Requesting Project member.
        project_id: Project whose plan is reopened.

    Returns:
        The Project with ``milestone_plan_status`` set back to ``draft``.

    Raises:
        HTTPException(403): If the user is not a Project member.
        HTTPException(409): If the plan is not finalized, or a Milestone is funded.
    """
    # Capture the id before the rollback below expires the auth-loaded User.
    user_id = user.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project, proposal = await _load_project_with_accepted_proposal(
            db=db,
            project_id=project_id,
            lock_project=True,
            lock_proposal=True,
        )
        await _ensure_project_member(db, project, proposal, user_id)
        if project.milestone_plan_status != "finalized":
            raise HTTPException(
                status_code=409,
                detail="Only a finalized Milestone plan can be reopened.",
            )
        funded_count = await db.scalar(
            select(func.count(Milestone.id)).where(
                Milestone.project_id == project.id,
                Milestone.status != "pending",
            )
        )
        if int(funded_count or 0) > 0:
            raise HTTPException(
                status_code=409,
                detail="Cannot reopen the plan after a Milestone has been funded.",
            )
        project.milestone_plan_status = "draft"
        db.add(
            _workspace_system_message(
                project_id=project.id,
                system_event="milestone_plan_reopened",
                payload={"reopened_by": str(user_id)},
            )
        )
        await write_audit(
            db=db,
            actor_id=user_id,
            action="milestone_plan_reopened",
            target_type="project",
            target_id=project.id,
            metadata={"accepted_proposal_id": str(proposal.id)},
        )
        await db.flush()
        await db.refresh(project)
    return project


async def _create_stripe_funding_customer(
    *,
    operator_id: UUID,
    operator_email: str,
    operator_display_name: str | None,
    project_id: UUID,
    milestone_id: UUID,
) -> str:
    """Create the Stripe Customer a Milestone funding intent is billed to.

    Raises:
        HTTPException(502): Stripe could not create the customer.
    """
    try:
        customer = await stripe.create_customer(
            email=operator_email,
            name=operator_display_name,
            idempotency_key=f"stripe_customer:{operator_id}",
        )
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
    return customer.id


async def fund_milestone(
    *,
    db: AsyncSession,
    operator: User,
    project_id: UUID,
    milestone_id: UUID,
    country: str | None = None,
) -> MilestoneFundingResponse:
    """Start escrow funding for a finalized Milestone on the payer's rail.

    The optional billing country picks the payment rail exactly as self-serve
    checkout does: Nigeria routes to Paystack hosted checkout, everything else
    (and an omitted country) stays on Stripe PaymentIntents. Enforces
    FR-FIN-005 on both corridors.
    """
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

    if currency != platform_currency():
        raise HTTPException(
            status_code=422,
            detail=f"Only {platform_currency()} Milestone funding is supported.",
        )

    requested_provider = select_provider(user_country=country, currency=currency)
    if requested_provider == "stripe" and customer_id is None:
        customer_id = await _create_stripe_funding_customer(
            operator_id=operator_id,
            operator_email=operator_email,
            operator_display_name=operator_display_name,
            project_id=project_id,
            milestone_id=milestone_id,
        )

    transaction_id, _, amount, currency, provider = (
        await _create_pending_milestone_transaction(
            db=db,
            operator_id=operator_id,
            customer_id=customer_id if requested_provider == "stripe" else None,
            project_id=project_id,
            milestone_id=milestone_id,
            provider=requested_provider,
        )
    )

    if provider == "paystack":
        return await _start_paystack_milestone_funding(
            db=db,
            operator_id=operator_id,
            operator_email=operator_email,
            transaction_id=transaction_id,
            project_id=project_id,
            milestone_id=milestone_id,
            amount=amount,
            currency=currency,
        )

    # A Stripe-initiated attempt resumed under a Paystack-routed request lands
    # here with no customer created yet; the stored rail wins, so make one now.
    if customer_id is None:
        customer_id = await _create_stripe_funding_customer(
            operator_id=operator_id,
            operator_email=operator_email,
            operator_display_name=operator_display_name,
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


async def _start_paystack_org_milestone_funding(
    *,
    db: AsyncSession,
    org_id: UUID,
    actor_id: UUID,
    billing_email: str,
    transaction_id: UUID,
    project_id: UUID,
    milestone_id: UUID,
    amount: Decimal,
    currency: str,
) -> MilestoneFundingResponse:
    """Initialize Paystack hosted checkout for an org Milestone funding.

    Org sibling of `_start_paystack_milestone_funding`: the charge bills the
    org's billing contact and the escrow metadata carries `payer_org_id` and
    `approver_org_id` so settlement and approval resolve to the organization.

    Raises:
        HTTPException(502): Paystack could not initialize the charge. The
            pending transaction is marked failed first so it never strands.
    """
    release_conditions = {
        "kind": "project_milestone",
        "milestone_id": str(milestone_id),
        "project_id": str(project_id),
        "approver_org_id": str(org_id),
    }
    try:
        initialized = await paystack.initialize_transaction(
            email=billing_email,
            amount=amount,
            currency=currency,
            metadata={
                "transaction_id": str(transaction_id),
                "kind": "escrow",
                "project_id": str(project_id),
                "milestone_id": str(milestone_id),
                "payer_org_id": str(org_id),
                "release_conditions": json.dumps(release_conditions),
            },
        )
    except PaystackProviderError as exc:
        await _mark_milestone_funding_failed(
            db=db,
            operator_id=actor_id,
            transaction_id=transaction_id,
            project_id=project_id,
            milestone_id=milestone_id,
            provider="paystack",
        )
        logger.bind(
            module="projects",
            action="fund_org_milestone",
            user_id=actor_id,
            org_id=org_id,
            project_id=project_id,
            milestone_id=milestone_id,
            transaction_id=transaction_id,
        ).error("paystack_initialize_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    await _mark_milestone_funding_provider_ref(
        db=db,
        operator_id=actor_id,
        transaction_id=transaction_id,
        provider_ref=initialized.reference,
        project_id=project_id,
        milestone_id=milestone_id,
        provider="paystack",
    )
    logger.bind(
        module="projects",
        action="fund_org_milestone",
        user_id=actor_id,
        org_id=org_id,
        project_id=project_id,
        milestone_id=milestone_id,
        transaction_id=transaction_id,
    ).info("milestone_funding_initiated")
    return MilestoneFundingResponse(
        transaction_id=transaction_id,
        provider="paystack",
        authorization_url=initialized.authorization_url,
    )


async def fund_org_milestone(
    *,
    db: AsyncSession,
    org_id: UUID,
    actor_id: UUID,
    project_id: UUID,
    milestone_id: UUID,
    country: str | None = None,
) -> MilestoneFundingResponse:
    """Fund a finalized Milestone of an org-operated Project from the org customer.

    Org sibling of :func:`fund_milestone`. The funding ``Transaction`` is stamped
    ``payer_org_id`` (``payer_id`` NULL) and the Stripe charge draws the
    organization's own Stripe customer. The org customer is never created lazily:
    a missing ``stripe_customer_id`` returns 402, mirroring the org purchase
    pay-in. Because an org has no single approving user, the Escrow
    ``release_conditions`` carries ``approver_org_id`` (approval authority
    resolves to the org's owner/admins at approval time) instead of the single
    ``approver_user_id`` used on the individual path.

    Args:
        db: Async SQLAlchemy session.
        org_id: The operating organization's id.
        actor_id: The acting org owner/admin user id (audit actor).
        project_id: The org-operated Project whose Milestone is funded.
        milestone_id: The finalized, pending Milestone to fund.

    Returns:
        The funding response with the Stripe client secret for the org payer.

    Raises:
        HTTPException(403): If the org Operator capability is not active.
        HTTPException(402): If the organization has no Stripe customer on file.
        HTTPException(404): If the Project is not operated by this organization.
        HTTPException(422): If the Milestone plan is unfinalized or non-USD.
        HTTPException(502): If the payment provider is unavailable.
    """
    from app.modules.organizations.models import Organization
    from app.modules.organizations.operator_service import operator_capability_active

    if not await operator_capability_active(db, org_id=org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "capability_suspended"},
        )

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        _, _, milestone = await _load_org_project_milestone_for_funding(
            db=db,
            project_id=project_id,
            milestone_id=milestone_id,
            org_id=org_id,
        )
        currency = milestone.currency.upper()
        organization = await db.get(Organization, org_id)
        customer_id = (
            organization.stripe_customer_id if organization is not None else None
        )
        # Captured while the org row is fresh: later commits expire it, and
        # the Paystack leg bills the org's billing contact.
        org_billing_email = (
            organization.billing_email if organization is not None else None
        )
        org_created_by = (
            organization.created_by if organization is not None else None
        )

    if currency != platform_currency():
        raise HTTPException(
            status_code=422,
            detail=f"Only {platform_currency()} Milestone funding is supported.",
        )

    requested_provider = select_provider(user_country=country, currency=currency)
    if requested_provider == "stripe" and customer_id is None:
        # No lazy org-customer create on the org path (mirrors org purchase).
        # The Paystack rail has no stored-payment-method concept and needs none.
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Organization has no payment method on file.",
        )

    transaction_id, amount, currency, provider = (
        await _create_pending_org_milestone_transaction(
            db=db,
            org_id=org_id,
            actor_id=actor_id,
            project_id=project_id,
            milestone_id=milestone_id,
            provider=requested_provider,
        )
    )

    if provider == "paystack":
        billing_email = org_billing_email
        if billing_email is None and org_created_by is not None:
            owner = await db.get(User, org_created_by)
            billing_email = owner.email if owner is not None else None
        if billing_email is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Organization has no billing contact.",
            )
        return await _start_paystack_org_milestone_funding(
            db=db,
            org_id=org_id,
            actor_id=actor_id,
            billing_email=billing_email,
            transaction_id=transaction_id,
            project_id=project_id,
            milestone_id=milestone_id,
            amount=amount,
            currency=currency,
        )

    if customer_id is None:
        # A Stripe-initiated attempt resumed under a Paystack-routed request
        # lands here; the stored rail wins but the customer must still exist.
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Organization has no payment method on file.",
        )
    release_conditions = {
        "kind": "project_milestone",
        "milestone_id": str(milestone_id),
        "project_id": str(project_id),
        "approver_org_id": str(org_id),
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
                "payer_org_id": str(org_id),
                "release_conditions": json.dumps(release_conditions),
            },
            idempotency_key=f"milestone_funding:{transaction_id}",
        )
    except StripeProviderError as exc:
        await _mark_milestone_funding_failed(
            db=db,
            operator_id=actor_id,
            transaction_id=transaction_id,
            project_id=project_id,
            milestone_id=milestone_id,
        )
        logger.bind(
            module="projects",
            action="fund_org_milestone",
            user_id=actor_id,
            org_id=org_id,
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
        operator_id=actor_id,
        transaction_id=transaction_id,
        provider_ref=payment_intent.id,
        project_id=project_id,
        milestone_id=milestone_id,
    )
    logger.bind(
        module="projects",
        action="fund_org_milestone",
        user_id=actor_id,
        org_id=org_id,
        project_id=project_id,
        milestone_id=milestone_id,
        transaction_id=transaction_id,
    ).info("milestone_funding_initiated")
    return MilestoneFundingResponse(
        transaction_id=transaction_id,
        provider="stripe",
        client_secret=payment_intent.client_secret,
    )


async def _ensure_workspace_file_keys(
    db: AsyncSession,
    *,
    project_id: UUID,
    file_keys: list[str],
) -> None:
    """Reject Deliverable file keys not uploaded to this project's workspace.

    The download endpoint presigns whatever keys a submission carried, and
    Framework artifacts live in the same bucket as workspace uploads. Without
    this check a Contributor could submit
    ``frameworks/<id>/artifacts/<id>.pdf`` — both ids are public on Explore —
    and pull any licensed artifact through their own Project, bypassing the
    licence gate. Keys are therefore matched against the upload sessions this
    project actually issued.

    Raises:
        HTTPException(422): Any key has no matching workspace upload session.
    """
    if not file_keys:
        return
    known = set(
        (
            await db.execute(
                select(WorkspaceUploadSession.s3_key).where(
                    WorkspaceUploadSession.project_id == project_id,
                    WorkspaceUploadSession.s3_key.in_(file_keys),
                )
            )
        )
        .scalars()
        .all()
    )
    unknown = [key for key in file_keys if key not in known]
    if unknown:
        logger.bind(
            module="projects",
            action="submit_deliverable",
            project_id=project_id,
        ).warning("deliverable_file_key_outside_workspace", rejected=len(unknown))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Deliverable files must be uploaded to this Project workspace.",
        )


async def submit_deliverable(
    *,
    db: AsyncSession,
    contributor: User,
    project_id: UUID,
    milestone_id: UUID,
    payload: DeliverableSubmitRequest,
) -> Deliverable:
    """Submit a Deliverable against a funded or revision-requested Milestone."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()

    now = datetime.now(UTC)
    async with db.begin():
        (
            project,
            proposal,
            milestone,
        ) = await _load_project_milestone_for_workspace_action(
            db=db,
            project_id=project_id,
            milestone_id=milestone_id,
        )
        deliverable_contributor_id, deliverable_contributor_org_id = (
            await _resolve_workspace_contributor_seller(
                db,
                proposal=proposal,
                contributor_id=contributor_id,
            )
        )
        if milestone.status not in {"funded", "revision_requested"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Deliverables can only be submitted for funded Milestones.",
            )
        await _ensure_workspace_file_keys(
            db,
            project_id=project.id,
            file_keys=payload.file_keys,
        )
        deliverable = Deliverable(
            milestone_id=milestone.id,
            contributor_id=deliverable_contributor_id,
            contributor_org_id=deliverable_contributor_org_id,
            name=payload.name,
            description=payload.description,
            file_keys=payload.file_keys,
            status="submitted",
            submitted_at=now,
        )
        db.add(deliverable)
        await db.flush()
        milestone.status = "submitted"
        milestone.submitted_at = now
        db.add(
            _workspace_system_message(
                project_id=project.id,
                system_event="deliverable_submitted",
                payload={
                    "milestone_id": str(milestone.id),
                    "deliverable_id": str(deliverable.id),
                },
            )
        )
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="deliverable_submitted",
            target_type="deliverable",
            target_id=deliverable.id,
            metadata={"project_id": str(project.id), "milestone_id": str(milestone.id)},
        )
        # Resolve the Operator-side recipients inside the transaction: the
        # individual Operator, or every owner/admin of the operating org.
        operator_recipient_ids = await resolve_operator_recipient_user_ids(
            db, project=project
        )
        await db.flush()
        await db.refresh(deliverable)
    # Dispatch the virus scan after commit so the worker can read the row; the
    # Deliverable stays pending_scan and approval is blocked until it is clean.
    scan_deliverable_upload.delay(str(deliverable.id))
    for operator_id in operator_recipient_ids:
        project_notifications.notify_deliverable_submitted(
            operator_id=operator_id,
            project_id=project_id,
            milestone_id=milestone_id,
            deliverable_id=deliverable.id,
            operator_org_id=project.operator_org_id,
        )
    return deliverable


async def _request_deliverable_revision(
    *,
    db: AsyncSession,
    actor_id: UUID,
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
    payload: DeliverableRevisionRequest,
    operator_org_id: UUID | None,
) -> Deliverable:
    """Request revision using either an individual or organization Operator."""
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project, proposal, milestone = (
            await _load_project_milestone_for_workspace_action(
                db=db,
                project_id=project_id,
                milestone_id=milestone_id,
            )
        )
        if operator_org_id is not None and project.operator_org_id != operator_org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found.",
            )
        if operator_org_id is None and project.operator_id != actor_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the Project Operator can request revisions.",
            )
        if milestone.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only submitted Milestones can be sent for revision.",
            )
        deliverable = await _load_deliverable_for_update(
            db=db,
            milestone_id=milestone.id,
            deliverable_id=deliverable_id,
        )
        if deliverable.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only submitted Deliverables can be sent for revision.",
            )
        deliverable.status = "revision_requested"
        deliverable.revision_notes = payload.revision_notes
        milestone.status = "revision_requested"
        db.add(
            _workspace_system_message(
                project_id=project.id,
                system_event="deliverable_revision_requested",
                payload={
                    "milestone_id": str(milestone.id),
                    "deliverable_id": str(deliverable.id),
                },
            )
        )
        audit_metadata = {
            "project_id": str(project.id),
            "milestone_id": str(milestone.id),
        }
        if operator_org_id is not None:
            audit_metadata["operator_org_id"] = str(operator_org_id)
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="deliverable_revision_requested",
            target_type="deliverable",
            target_id=deliverable.id,
            metadata=audit_metadata,
        )
        revision_contributor_id = await _proposal_workspace_user_id(
            db, proposal=proposal
        )
        await db.flush()
        await db.refresh(deliverable)

    project_notifications.notify_deliverable_revision_requested(
        contributor_id=revision_contributor_id,
        project_id=project_id,
        milestone_id=milestone_id,
        deliverable_id=deliverable.id,
    )
    return deliverable


async def request_deliverable_revision(
    *,
    db: AsyncSession,
    operator: User,
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
    payload: DeliverableRevisionRequest,
) -> Deliverable:
    """Request revision on a submitted Deliverable as Project Operator."""
    return await _request_deliverable_revision(
        db=db,
        actor_id=operator.id,
        project_id=project_id,
        milestone_id=milestone_id,
        deliverable_id=deliverable_id,
        payload=payload,
        operator_org_id=None,
    )


async def request_org_deliverable_revision(
    *,
    db: AsyncSession,
    org_id: UUID,
    actor_id: UUID,
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
    payload: DeliverableRevisionRequest,
) -> Deliverable:
    """Request revision on work submitted to an organization-operated Project."""
    return await _request_deliverable_revision(
        db=db,
        actor_id=actor_id,
        project_id=project_id,
        milestone_id=milestone_id,
        deliverable_id=deliverable_id,
        payload=payload,
        operator_org_id=org_id,
    )


async def approve_deliverable(
    *,
    db: AsyncSession,
    operator: User,
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
) -> Deliverable:
    """Approve a submitted Deliverable and release its Milestone escrow."""
    operator_id = operator.id
    if db.in_transaction():
        await db.rollback()

    now = datetime.now(UTC)
    async with db.begin():
        project, proposal, milestone = (
            await _load_project_milestone_for_workspace_action(
                db=db,
                project_id=project_id,
                milestone_id=milestone_id,
            )
        )
        if project.operator_id != operator_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the Project Operator can approve Deliverables.",
            )
        if milestone.status != "submitted" or milestone.escrow_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only submitted escrow-backed Milestones can be approved.",
            )
        deliverable = await _load_deliverable_for_update(
            db=db,
            milestone_id=milestone.id,
            deliverable_id=deliverable_id,
        )
        if deliverable.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only submitted Deliverables can be approved.",
            )
        # Never release Escrow for a Deliverable whose files have not passed the
        # virus scan; a quarantined file must be re-submitted, not approved.
        if deliverable.scan_status != "visible":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Deliverable files are still being scanned or were "
                    "quarantined; approval is blocked."
                ),
            )
        await db.scalar(
            select(Escrow).where(Escrow.id == milestone.escrow_id).with_for_update()
        )
        await escrow_service.release(
            db,
            escrow_id=milestone.escrow_id,
            actor_id=operator_id,
            reason="deliverable_approved",
        )
        deliverable.status = "approved"
        deliverable.approved_at = now
        milestone.status = "approved"
        milestone.approved_at = now
        await _maybe_mark_project_delivered(db, project=project, now=now)
        db.add(
            _workspace_system_message(
                project_id=project.id,
                system_event="deliverable_approved",
                payload={
                    "milestone_id": str(milestone.id),
                    "deliverable_id": str(deliverable.id),
                },
            )
        )
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="deliverable_approved",
            target_type="deliverable",
            target_id=deliverable.id,
            metadata={"project_id": str(project.id), "milestone_id": str(milestone.id)},
        )
        approved_contributor_id = await _proposal_workspace_user_id(
            db, proposal=proposal
        )
        await db.flush()
        await db.refresh(deliverable)

    project_notifications.notify_deliverable_approved(
        contributor_id=approved_contributor_id,
        project_id=project_id,
        milestone_id=milestone_id,
        deliverable_id=deliverable.id,
    )
    return deliverable


async def _resolve_deliverable_milestone_id(
    *,
    db: AsyncSession,
    deliverable_id: UUID,
) -> UUID:
    """Return the Milestone id owning a Deliverable, or raise 404."""
    milestone_id = await db.scalar(
        select(Deliverable.milestone_id).where(Deliverable.id == deliverable_id)
    )
    if milestone_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deliverable not found.",
        )
    return milestone_id


async def approve_org_deliverable(
    *,
    db: AsyncSession,
    org_id: UUID,
    actor_id: UUID,
    project_id: UUID,
    deliverable_id: UUID,
) -> Deliverable:
    """Approve a Deliverable for an org-operated Project and release its Escrow.

    Org sibling of :func:`approve_deliverable`. The Milestone is resolved from the
    Deliverable (the org endpoint addresses the Deliverable directly), the Project
    is matched on ``operator_org_id`` (cross-org access surfaces as 404), and the
    acting org owner/admin is recorded as the release actor. The Escrow
    beneficiary resolution is unchanged — :func:`escrow_service.release` still
    credits the accepted Contributor (an individual Contributor via ``payee_id``
    or an org Contributor via ``payee_org_id``). Only the funding payer differs on
    the org path. Requires the org Operator capability to be active.

    Args:
        db: Async SQLAlchemy session.
        org_id: The operating organization's id.
        actor_id: The acting org owner/admin user id (release + audit actor).
        project_id: The org-operated Project whose Deliverable is approved.
        deliverable_id: The submitted, scanned Deliverable to approve.

    Returns:
        The approved Deliverable.

    Raises:
        HTTPException(403): If the org Operator capability is not active.
        HTTPException(404): If the Project/Deliverable is not found for this org.
        HTTPException(409): If the Milestone/Deliverable is not approvable.
    """
    from app.modules.organizations.operator_service import operator_capability_active

    if not await operator_capability_active(db, org_id=org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "capability_suspended"},
        )
    if db.in_transaction():
        await db.rollback()

    now = datetime.now(UTC)
    async with db.begin():
        milestone_id = await _resolve_deliverable_milestone_id(
            db=db,
            deliverable_id=deliverable_id,
        )
        project, proposal, milestone = (
            await _load_project_milestone_for_workspace_action(
                db=db,
                project_id=project_id,
                milestone_id=milestone_id,
            )
        )
        if project.operator_org_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found.",
            )
        if milestone.status != "submitted" or milestone.escrow_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only submitted escrow-backed Milestones can be approved.",
            )
        deliverable = await _load_deliverable_for_update(
            db=db,
            milestone_id=milestone.id,
            deliverable_id=deliverable_id,
        )
        if deliverable.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only submitted Deliverables can be approved.",
            )
        if deliverable.scan_status != "visible":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Deliverable files are still being scanned or were "
                    "quarantined; approval is blocked."
                ),
            )
        await db.scalar(
            select(Escrow).where(Escrow.id == milestone.escrow_id).with_for_update()
        )
        await escrow_service.release(
            db,
            escrow_id=milestone.escrow_id,
            actor_id=actor_id,
            reason="deliverable_approved",
        )
        deliverable.status = "approved"
        deliverable.approved_at = now
        milestone.status = "approved"
        milestone.approved_at = now
        await _maybe_mark_project_delivered(db, project=project, now=now)
        db.add(
            _workspace_system_message(
                project_id=project.id,
                system_event="deliverable_approved",
                payload={
                    "milestone_id": str(milestone.id),
                    "deliverable_id": str(deliverable.id),
                },
            )
        )
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="deliverable_approved",
            target_type="deliverable",
            target_id=deliverable.id,
            metadata={
                "project_id": str(project.id),
                "milestone_id": str(milestone.id),
                "operator_org_id": str(org_id),
            },
        )
        approved_contributor_id = await _proposal_workspace_user_id(
            db, proposal=proposal
        )
        await db.flush()
        await db.refresh(deliverable)

    project_notifications.notify_deliverable_approved(
        contributor_id=approved_contributor_id,
        project_id=project_id,
        milestone_id=milestone_id,
        deliverable_id=deliverable.id,
    )
    return deliverable


async def build_framework_prefill_from_deliverable(
    *,
    db: AsyncSession,
    contributor: User,
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
) -> FrameworkPrefillResponse:
    """Build Framework form prefill data from an approved Project Deliverable."""
    project, proposal, milestone = await _load_project_milestone_for_workspace_action(
        db=db,
        project_id=project_id,
        milestone_id=milestone_id,
        lock_project=False,
        lock_milestone=False,
    )
    await _ensure_accepted_contributor(db, proposal, contributor.id)
    deliverable = await db.scalar(
        select(Deliverable).where(
            Deliverable.id == deliverable_id,
            Deliverable.milestone_id == milestone.id,
            Deliverable.contributor_id == contributor.id,
        )
    )
    if deliverable is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deliverable not found.",
        )
    if deliverable.status not in {"approved", "auto_approved"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only approved Deliverables can prefill Framework drafts.",
        )
    return FrameworkPrefillResponse(
        title=deliverable.name,
        description=deliverable.description,
        file_keys=deliverable.file_keys,
        source_project_id=project.id,
        source_deliverable_id=deliverable.id,
    )


async def close_delivered_project(
    *,
    db: AsyncSession,
    operator: User,
    project_id: UUID,
) -> Project:
    """Close a delivered Project as an archive action."""
    operator_id = operator.id
    if db.in_transaction():
        await db.rollback()

    now = datetime.now(UTC)
    async with db.begin():
        project = await db.scalar(
            select(Project)
            .where(Project.id == project_id, Project.operator_id == operator_id)
            .with_for_update()
        )
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found.",
            )
        if project.status != "delivered":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only delivered Projects can be closed.",
            )
        active_disputes = await db.scalar(
            select(func.count(Dispute.id)).where(
                Dispute.project_id == project.id,
                Dispute.status.in_(("open", "under_review")),
            )
        )
        if int(active_disputes or 0) > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Projects with active disputes cannot be closed.",
            )
        project.status = "closed"
        project.closed_at = now
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="project_closed",
            target_type="project",
            target_id=project.id,
            metadata={"reason": "delivered_project_archived"},
        )
        await db.flush()
        await db.refresh(project)
    return project
