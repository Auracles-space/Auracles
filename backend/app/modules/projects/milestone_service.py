"""Milestone drafting and finalization services for Project workspaces."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.auth.models import User
from app.modules.projects.models import Milestone, Project, Proposal
from app.modules.projects.schemas import (
    MilestoneCreateRequest,
    MilestonesResponse,
    MilestoneUpdateRequest,
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
