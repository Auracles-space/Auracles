"""Dispute lifecycle services for Project milestones.

Project members use this module to raise and read milestone disputes. Admins use
the same boundary to resolve disputes with release, refund, or split outcomes.
All state changes are kept in one transaction with escrow updates, audit rows,
and workspace system messages so financial and collaboration state cannot drift.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.audit import write_audit
from app.integrations import stripe
from app.integrations.stripe import StripeProviderError
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.financials import escrow_service
from app.modules.financials.models import Escrow, Transaction
from app.modules.projects.models import (
    Deliverable,
    Dispute,
    Milestone,
    Project,
    Proposal,
)
from app.modules.projects.schemas import (
    AdminDisputeResponse,
    AdminDisputesResponse,
    DisputeCreateRequest,
    DisputeResponse,
    DisputesResponse,
)
from app.modules.workspace.models import WorkspaceMessage
from app.workers.tasks.project_notifications import dispatch_project_notification

ACTIVE_DISPUTE_STATUSES = ("open", "under_review")
TERMINAL_DISPUTE_BLOCKED_MILESTONES = ("approved", "auto_approved", "cancelled")
ACTIVE_MILESTONE_STATUSES = ("funded", "submitted", "revision_requested")
TERMINAL_MILESTONE_STATUSES = ("approved", "auto_approved", "cancelled")


def _normalise_money(amount: Decimal) -> Decimal:
    """Return a two-decimal money value for dispute comparisons."""
    return amount.quantize(Decimal("0.01"))


def _ensure_project_member(project: Project, proposal: Proposal, user_id: UUID) -> None:
    """Raise unless a user belongs to the Project workspace."""
    if user_id not in {project.operator_id, proposal.contributor_id}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Project members can access disputes.",
        )


async def _load_project_with_accepted_proposal(
    *,
    db: AsyncSession,
    project_id: UUID,
    lock_project: bool = False,
    lock_proposal: bool = False,
) -> tuple[Project, Proposal]:
    """Load a Project and accepted Proposal, optionally under row locks."""
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
            detail="Disputes require an accepted Proposal.",
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


async def _load_project_member_context(
    *,
    db: AsyncSession,
    project_id: UUID,
    user_id: UUID,
    lock_project: bool = False,
    lock_proposal: bool = False,
) -> tuple[Project, Proposal]:
    """Load accepted Project rows and authorize the current member."""
    project, proposal = await _load_project_with_accepted_proposal(
        db=db,
        project_id=project_id,
        lock_project=lock_project,
        lock_proposal=lock_proposal,
    )
    _ensure_project_member(project, proposal, user_id)
    return project, proposal


async def _load_milestone_for_dispute(
    *,
    db: AsyncSession,
    project_id: UUID,
    milestone_id: UUID,
) -> Milestone:
    """Load a disputable Milestone under lock or raise a typed error."""
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
    if milestone.status in TERMINAL_DISPUTE_BLOCKED_MILESTONES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Terminal Milestones cannot be disputed.",
        )
    if milestone.escrow_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only escrow-funded Milestones can be disputed.",
        )
    return milestone


async def _reject_duplicate_active_dispute(
    *,
    db: AsyncSession,
    milestone_id: UUID,
) -> None:
    """Reject a second active dispute for the same Milestone."""
    active_dispute_id = await db.scalar(
        select(Dispute.id)
        .where(
            Dispute.milestone_id == milestone_id,
            Dispute.status.in_(ACTIVE_DISPUTE_STATUSES),
        )
        .limit(1)
    )
    if active_dispute_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Milestone already has an active dispute.",
        )


async def _recompute_project_status(
    db: AsyncSession,
    *,
    project: Project,
    now: datetime,
) -> None:
    """Apply the post-dispute Project status recomputation rules."""
    active_dispute_id = await db.scalar(
        select(Dispute.id)
        .where(
            Dispute.project_id == project.id,
            Dispute.status.in_(ACTIVE_DISPUTE_STATUSES),
        )
        .limit(1)
    )
    if active_dispute_id is not None:
        project.status = "disputed"
        return

    active_milestone_id = await db.scalar(
        select(Milestone.id)
        .where(
            Milestone.project_id == project.id,
            Milestone.status.in_(ACTIVE_MILESTONE_STATUSES),
        )
        .limit(1)
    )
    if active_milestone_id is not None:
        project.status = "in_progress"
        return

    total_count = await db.scalar(
        select(func.count(Milestone.id)).where(Milestone.project_id == project.id)
    )
    terminal_count = await db.scalar(
        select(func.count(Milestone.id)).where(
            Milestone.project_id == project.id,
            Milestone.status.in_(TERMINAL_MILESTONE_STATUSES),
        )
    )
    if int(total_count or 0) > 0 and int(total_count or 0) == int(terminal_count or 0):
        project.status = "delivered"
        project.delivered_at = project.delivered_at or now
        return
    project.status = "assigned"


async def _mark_latest_deliverables_approved(
    db: AsyncSession,
    *,
    milestone_id: UUID,
    now: datetime,
) -> None:
    """Mark submitted or revision-requested Deliverables approved after release."""
    deliverables = (
        (
            await db.execute(
                select(Deliverable)
                .where(
                    Deliverable.milestone_id == milestone_id,
                    Deliverable.status.in_(("submitted", "revision_requested")),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for deliverable in deliverables:
        deliverable.status = "approved"
        deliverable.approved_at = now


def _queue_dispute_notification(
    *,
    user_id: UUID,
    notification_type: str,
    title: str,
    body: str,
    project_id: UUID,
    dispute_id: UUID,
    dedupe_key: str,
) -> None:
    """Dispatch a recoverable in-app/email notification after commit."""
    dispatch_project_notification.delay(
        user_id=str(user_id),
        notification_type=notification_type,
        title=title,
        body=body,
        payload={"project_id": str(project_id), "dispute_id": str(dispute_id)},
        link=f"/projects/{project_id}",
        dedupe_key=dedupe_key,
    )


async def create_dispute(
    *,
    db: AsyncSession,
    actor: User,
    project_id: UUID,
    payload: DisputeCreateRequest,
) -> Dispute:
    """Raise an active dispute against an escrow-funded Project Milestone."""
    actor_id = actor.id
    if db.in_transaction():
        await db.rollback()

    notify_user_ids: list[UUID] = []
    async with db.begin():
        project, proposal = await _load_project_member_context(
            db=db,
            project_id=project_id,
            user_id=actor_id,
            lock_project=True,
            lock_proposal=True,
        )
        milestone = await _load_milestone_for_dispute(
            db=db,
            project_id=project.id,
            milestone_id=payload.milestone_id,
        )
        await _reject_duplicate_active_dispute(db=db, milestone_id=milestone.id)

        dispute = Dispute(
            project_id=project.id,
            milestone_id=milestone.id,
            raised_by=actor_id,
            reason=payload.reason.strip(),
        )
        db.add(dispute)
        await db.flush()
        project.status = "disputed"
        milestone.status = "disputed"
        notify_user_ids = [
            user_id
            for user_id in (project.operator_id, proposal.contributor_id)
            if user_id != actor_id
        ]
        db.add(
            WorkspaceMessage(
                project_id=project.id,
                sender_id=None,
                system_event="dispute_raised",
                system_payload={
                    "dispute_id": str(dispute.id),
                    "milestone_id": str(milestone.id),
                    "raised_by": str(actor_id),
                },
            )
        )
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="dispute_raised",
            target_type="dispute",
            target_id=dispute.id,
            metadata={
                "project_id": str(project.id),
                "milestone_id": str(milestone.id),
            },
        )
        await db.flush()
        await db.refresh(dispute)

    for user_id in notify_user_ids:
        _queue_dispute_notification(
            user_id=user_id,
            notification_type="dispute_raised",
            title="Project dispute raised",
            body="A milestone dispute was raised on your project.",
            project_id=project_id,
            dispute_id=dispute.id,
            dedupe_key=f"dispute_raised:{dispute.id}:{user_id}",
        )
    return dispute


async def list_project_disputes(
    *,
    db: AsyncSession,
    user: User,
    project_id: UUID,
) -> DisputesResponse:
    """List disputes for a Project workspace member."""
    await _load_project_member_context(
        db=db,
        project_id=project_id,
        user_id=user.id,
    )
    rows = await db.execute(
        select(Dispute)
        .where(Dispute.project_id == project_id)
        .order_by(Dispute.created_at.desc())
    )
    return DisputesResponse(disputes=list(rows.scalars()))


_ADMIN_ACTIVE_DISPUTE_STATUSES = ("open", "under_review")


async def list_disputes_for_admin(
    *,
    db: AsyncSession,
    status_filter: str | None = None,
) -> AdminDisputesResponse:
    """List Project disputes across all Projects for the Admin queue.

    Admins do not belong to Project workspaces, so this bypasses the member
    check used by the workspace listing. Each row is enriched with the milestone
    budget, held escrow amount, project title, and the raising party's name so
    the resolver has the money context needed to choose a release/refund/split
    amount. The default view shows only active disputes (open or under_review);
    passing an explicit status narrows to that single status so resolved
    disputes remain auditable.

    Args:
        db: Async database session.
        status_filter: Optional exact status to filter by. When omitted, only
            active (open/under_review) disputes are returned.

    Returns:
        Disputes ordered newest-first, each with resolution context.
    """
    operator_user = aliased(User, name="operator_user")
    contributor_user = aliased(User, name="contributor_user")
    statement = (
        select(
            Dispute,
            Project,
            Milestone,
            Escrow,
            operator_user,
            contributor_user,
        )
        .join(Project, Project.id == Dispute.project_id)
        .join(Milestone, Milestone.id == Dispute.milestone_id)
        .outerjoin(Escrow, Escrow.id == Milestone.escrow_id)
        .join(operator_user, operator_user.id == Project.operator_id)
        .join(Proposal, Proposal.id == Project.accepted_proposal_id)
        .join(contributor_user, contributor_user.id == Proposal.contributor_id)
        .order_by(Dispute.created_at.desc())
    )
    if status_filter is None:
        statement = statement.where(Dispute.status.in_(_ADMIN_ACTIVE_DISPUTE_STATUSES))
    else:
        statement = statement.where(Dispute.status == status_filter)

    rows = await db.execute(statement)
    disputes: list[AdminDisputeResponse] = []
    for dispute, project, milestone, escrow, operator, contributor in rows.all():
        # The raiser is always one of the two parties; label which side acted.
        raised_by_operator = dispute.raised_by == operator.id
        raiser = operator if raised_by_operator else contributor
        disputes.append(
            AdminDisputeResponse(
                **DisputeResponse.model_validate(dispute).model_dump(),
                project_title=project.title,
                milestone_name=milestone.name,
                milestone_budget=milestone.budget,
                currency=milestone.currency,
                escrow_amount=escrow.amount if escrow is not None else None,
                escrow_status=escrow.status if escrow is not None else None,
                raised_by_name=raiser.display_name,
                raised_by_role="operator" if raised_by_operator else "contributor",
                operator_name=operator.display_name,
                contributor_name=contributor.display_name,
            )
        )
    return AdminDisputesResponse(disputes=disputes)


async def get_project_dispute(
    *,
    db: AsyncSession,
    user: User,
    project_id: UUID,
    dispute_id: UUID,
) -> Dispute:
    """Return one dispute visible to a Project workspace member."""
    await _load_project_member_context(
        db=db,
        project_id=project_id,
        user_id=user.id,
    )
    dispute = await db.scalar(
        select(Dispute).where(
            Dispute.id == dispute_id,
            Dispute.project_id == project_id,
        )
    )
    if dispute is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispute not found.",
        )
    return dispute


async def _verify_admin_2fa(
    db: AsyncSession,
    redis: Redis,
    admin_id: UUID,
    totp_code: str,
) -> None:
    """Require a valid admin TOTP before sensitive dispute resolution."""
    admin = await db.get(User, admin_id, with_for_update=True)
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        )
    await auth_service.verify_totp_for_sensitive_action(
        db=db,
        redis=redis,
        user=admin,
        code=totp_code,
    )


def _validate_resolution_amounts(
    *,
    resolution_type: str,
    milestone_budget: Decimal,
    release_amount: Decimal | None,
    refund_amount: Decimal | None,
) -> tuple[Decimal | None, Decimal | None]:
    """Validate resolution amounts against the locked Milestone budget."""
    budget = _normalise_money(milestone_budget)
    if resolution_type == "split":
        if release_amount is None or refund_amount is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Split resolution requires release and refund amounts.",
            )
        normalized_release = _normalise_money(release_amount)
        normalized_refund = _normalise_money(refund_amount)
        if normalized_release + normalized_refund != budget:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Split amounts must equal the Milestone budget.",
            )
        return normalized_release, normalized_refund
    if release_amount is not None or refund_amount is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Amounts are only accepted for split resolution.",
        )
    return None, None


async def _refund_escrow_to_stripe(
    *,
    escrow: Escrow,
    transaction: Transaction,
    reason: str,
) -> None:
    """Refund a full escrow amount through Stripe before local refund state."""
    if transaction.provider_ref is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Escrow funding transaction is missing provider metadata.",
        )
    if transaction.provider != "stripe":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unsupported escrow payment provider.",
        )
    try:
        await stripe.create_refund(
            payment_intent_id=transaction.provider_ref,
            amount=transaction.amount,
            currency=transaction.currency,
            idempotency_key=f"escrow_dispute_refund:{escrow.id}",
        )
    except StripeProviderError as exc:
        logger.bind(
            module="projects",
            action="resolve_dispute",
            escrow_id=escrow.id,
            transaction_id=transaction.id,
        ).error("stripe_dispute_refund_failed", error=str(exc), reason=reason)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc


async def resolve_dispute(
    *,
    db: AsyncSession,
    redis: Redis,
    admin: User,
    dispute_id: UUID,
    resolution_type: str,
    release_amount: Decimal | None,
    refund_amount: Decimal | None,
    resolution_notes: str,
    totp_code: str,
) -> Dispute:
    """Resolve a Project dispute and synchronize escrow/workspace state."""
    admin_id = admin.id
    if db.in_transaction():
        await db.rollback()

    notification_type = f"dispute_resolved_{resolution_type}"
    notify_user_ids: list[UUID] = []
    async with db.begin():
        await _verify_admin_2fa(
            db=db,
            redis=redis,
            admin_id=admin_id,
            totp_code=totp_code,
        )
        dispute = await db.scalar(
            select(Dispute).where(Dispute.id == dispute_id).with_for_update()
        )
        if dispute is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dispute not found.",
            )
        if dispute.status == "resolved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Resolved disputes cannot be resolved again.",
            )

        project, proposal = await _load_project_with_accepted_proposal(
            db=db,
            project_id=dispute.project_id,
            lock_project=True,
            lock_proposal=True,
        )
        milestone = await db.scalar(
            select(Milestone)
            .where(
                Milestone.id == dispute.milestone_id,
                Milestone.project_id == project.id,
            )
            .with_for_update()
        )
        if milestone is None or milestone.escrow_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dispute Milestone is missing escrow funding.",
            )
        escrow = await db.get(Escrow, milestone.escrow_id, with_for_update=True)
        if escrow is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Escrow not found.",
            )
        transaction = await db.get(
            Transaction,
            escrow.transaction_id,
            with_for_update=True,
        )
        if transaction is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Escrow funding transaction not found.",
            )

        normalized_release, normalized_refund = _validate_resolution_amounts(
            resolution_type=resolution_type,
            milestone_budget=milestone.budget,
            release_amount=release_amount,
            refund_amount=refund_amount,
        )
        now = datetime.now(UTC)
        if resolution_type == "release":
            await escrow_service.release(
                db,
                escrow_id=escrow.id,
                actor_id=admin_id,
                reason=resolution_notes,
                admin_override=True,
            )
            milestone.status = "approved"
            milestone.approved_at = now
            await _mark_latest_deliverables_approved(
                db,
                milestone_id=milestone.id,
                now=now,
            )
        elif resolution_type == "refund":
            await _refund_escrow_to_stripe(
                escrow=escrow,
                transaction=transaction,
                reason=resolution_notes,
            )
            await escrow_service.refund(
                db,
                escrow_id=escrow.id,
                actor_id=admin_id,
                reason=resolution_notes,
                admin_override=True,
            )
            milestone.status = "cancelled"
        else:
            assert normalized_release is not None
            assert normalized_refund is not None
            await escrow_service.split(
                db,
                escrow_id=escrow.id,
                actor_id=admin_id,
                release_amount=normalized_release,
                refund_amount=normalized_refund,
                reason=resolution_notes,
                admin_override=True,
            )
            milestone.status = "approved"
            milestone.approved_at = now
            await _mark_latest_deliverables_approved(
                db,
                milestone_id=milestone.id,
                now=now,
            )

        dispute.status = "resolved"
        dispute.resolution_type = resolution_type
        dispute.release_amount = normalized_release
        dispute.refund_amount = normalized_refund
        dispute.admin_id = admin_id
        dispute.resolution_notes = resolution_notes.strip()
        dispute.resolved_at = now
        await _recompute_project_status(db, project=project, now=now)
        notify_user_ids = [project.operator_id, proposal.contributor_id]
        db.add(
            WorkspaceMessage(
                project_id=project.id,
                sender_id=None,
                system_event="dispute_resolved",
                system_payload={
                    "dispute_id": str(dispute.id),
                    "milestone_id": str(milestone.id),
                    "resolution_type": resolution_type,
                    "release_amount": str(normalized_release)
                    if normalized_release is not None
                    else None,
                    "refund_amount": str(normalized_refund)
                    if normalized_refund is not None
                    else None,
                },
            )
        )
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="dispute_resolved",
            target_type="dispute",
            target_id=dispute.id,
            metadata={
                "project_id": str(project.id),
                "milestone_id": str(milestone.id),
                "resolution_type": resolution_type,
                "project_status": project.status,
                "milestone_status": milestone.status,
            },
        )
        await db.flush()
        await db.refresh(dispute)

    for user_id in notify_user_ids:
        _queue_dispute_notification(
            user_id=user_id,
            notification_type=notification_type,
            title="Project dispute resolved",
            body="An admin resolved a milestone dispute on your project.",
            project_id=dispute.project_id,
            dispute_id=dispute.id,
            dedupe_key=f"dispute_resolved:{dispute.id}:{user_id}",
        )
    return dispute
