"""Project and Proposal orchestration services.

Slice 4 covers the marketplace workflow up to assignment: Operators create and
manage open Projects, Contributors submit Proposals, and Operators accept one
Proposal to move the Project into the assigned state.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.auth.models import User
from app.modules.projects.models import Project, Proposal
from app.modules.projects.schemas import (
    DeliverableSpec,
    ProjectCreateRequest,
    ProjectsResponse,
    ProjectUpdateRequest,
    ProposalCreateRequest,
    ProposalsResponse,
)

ACTIVE_PROJECT_STATUSES = {
    "open",
    "assigned",
    "in_progress",
    "delivered",
    "disputed",
}
MAX_ACTIVE_PROJECTS = 5


def _project_query() -> Select[tuple[Project]]:
    """Return the base Project select used by read paths."""
    return select(Project)


async def _load_project(db: AsyncSession, project_id: UUID) -> Project:
    """Load a Project or raise a 404."""
    project = await db.scalar(_project_query().where(Project.id == project_id))
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    return project


def _serialize_deliverables(payload: Sequence[DeliverableSpec]) -> list[dict[str, str]]:
    """Convert Pydantic deliverable specs to JSONB-safe dictionaries."""
    return [item.model_dump() for item in payload]


async def create_project(
    *,
    db: AsyncSession,
    operator: User,
    payload: ProjectCreateRequest,
) -> Project:
    """Create an open Project while enforcing the MVP active-project cap."""
    operator_id = operator.id
    if db.in_transaction():
        await db.rollback()

    now = datetime.now(UTC)
    async with db.begin():
        # Lock the Operator row so concurrent creates serialize per account.
        await db.scalar(select(User).where(User.id == operator_id).with_for_update())
        active_count = await db.scalar(
            select(func.count(Project.id)).where(
                Project.operator_id == operator_id,
                Project.status.in_(ACTIVE_PROJECT_STATUSES),
            )
        )
        if int(active_count or 0) >= MAX_ACTIVE_PROJECTS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Operator has reached the maximum of 5 active Projects.",
            )

        project = Project(
            operator_id=operator_id,
            title=payload.title,
            description=payload.description,
            category=payload.category,
            required_deliverables=_serialize_deliverables(
                payload.required_deliverables
            ),
            budget_min=payload.budget_min,
            budget_max=payload.budget_max,
            currency=payload.currency,
            deadline=payload.deadline,
            expires_at=now + timedelta(days=30),
        )
        db.add(project)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="project_created",
            target_type="project",
            target_id=project.id,
            metadata={"title": project.title},
        )
        await db.flush()
        await db.refresh(project)
    return project


async def list_projects(
    *,
    db: AsyncSession,
    user: User,
    role: Literal["contributor", "operator"],
    token_roles: list[str],
    page: int,
    page_size: int,
) -> ProjectsResponse:
    """List open Contributor feed or Operator-owned Projects."""
    if role not in token_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requested Project role is not present in token.",
        )

    query = _project_query()
    if role == "contributor":
        query = query.where(Project.status == "open")
    else:
        query = query.where(Project.operator_id == user.id)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = await db.execute(
        query.order_by(Project.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return ProjectsResponse(
        projects=list(rows.scalars()),
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


async def get_project(
    *,
    db: AsyncSession,
    user: User,
    token_roles: list[str],
    project_id: UUID,
) -> Project:
    """Return a Project if the user can browse or belongs to it."""
    project = await _load_project(db, project_id)
    if project.operator_id == user.id:
        return project
    if project.status == "open" and "contributor" in token_roles:
        return project
    if project.accepted_proposal_id is not None:
        accepted = await db.scalar(
            select(Proposal).where(Proposal.id == project.accepted_proposal_id)
        )
        if accepted is not None and accepted.contributor_id == user.id:
            return project
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Project is not visible to this user.",
    )


async def update_project(
    *,
    db: AsyncSession,
    operator: User,
    project_id: UUID,
    payload: ProjectUpdateRequest,
) -> Project:
    """Update an Operator-owned Project while it is still open."""
    operator_id = operator.id
    if db.in_transaction():
        await db.rollback()

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
        if project.status != "open":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only open Projects can be edited.",
            )

        updates = payload.model_dump(exclude_unset=True)
        if "required_deliverables" in updates:
            updates["required_deliverables"] = _serialize_deliverables(
                payload.required_deliverables or []
            )
        budget_min = updates.get("budget_min", project.budget_min)
        budget_max = updates.get("budget_max", project.budget_max)
        if budget_min > budget_max:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="budget_max must be greater than or equal to budget_min.",
            )

        for key, value in updates.items():
            setattr(project, key, value)
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="project_extended" if "deadline" in updates else "project_updated",
            target_type="project",
            target_id=project.id,
            metadata={"updated_fields": sorted(updates.keys())},
        )
        await db.flush()
        await db.refresh(project)
    return project


async def submit_proposal(
    *,
    db: AsyncSession,
    contributor: User,
    project_id: UUID,
    payload: ProposalCreateRequest,
) -> Proposal:
    """Submit a Contributor Proposal against an open Project."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project = await db.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found.",
            )
        if project.status != "open":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Proposals can only be submitted to open Projects.",
            )
        if project.operator_id == contributor_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Operators cannot propose on their own Projects.",
            )

        existing = await db.scalar(
            select(Proposal).where(
                Proposal.project_id == project_id,
                Proposal.contributor_id == contributor_id,
                Proposal.status.in_(("pending", "accepted")),
            )
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Contributor already has an active Proposal for this Project.",
            )

        proposal = Proposal(
            project_id=project_id,
            contributor_id=contributor_id,
            scope=payload.scope,
            budget=payload.budget,
            currency=payload.currency,
            timeline_days=payload.timeline_days,
            deliverables=_serialize_deliverables(payload.deliverables),
        )
        db.add(proposal)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="proposal_submitted",
            target_type="proposal",
            target_id=proposal.id,
            metadata={"project_id": str(project_id)},
        )
        await db.flush()
        await db.refresh(proposal)
    return proposal


async def list_project_proposals(
    *,
    db: AsyncSession,
    operator: User,
    project_id: UUID,
) -> ProposalsResponse:
    """List Proposals for an Operator-owned Project."""
    project = await db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.operator_id == operator.id,
        )
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    proposals = (
        (
            await db.execute(
                select(Proposal)
                .where(Proposal.project_id == project_id)
                .order_by(Proposal.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return ProposalsResponse(proposals=list(proposals))


async def list_my_project_proposals(
    *,
    db: AsyncSession,
    contributor: User,
    project_id: UUID,
) -> ProposalsResponse:
    """List the current Contributor's Proposals for one Project."""
    proposals = (
        (
            await db.execute(
                select(Proposal)
                .where(
                    Proposal.project_id == project_id,
                    Proposal.contributor_id == contributor.id,
                )
                .order_by(Proposal.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return ProposalsResponse(proposals=list(proposals))


async def withdraw_proposal(
    *,
    db: AsyncSession,
    contributor: User,
    project_id: UUID,
    proposal_id: UUID,
) -> Proposal:
    """Withdraw the current Contributor's pending Proposal."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        proposal = await db.scalar(
            select(Proposal)
            .where(
                Proposal.id == proposal_id,
                Proposal.project_id == project_id,
                Proposal.contributor_id == contributor_id,
            )
            .with_for_update()
        )
        if proposal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proposal not found.",
            )
        if proposal.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only pending Proposals can be withdrawn.",
            )
        proposal.status = "withdrawn"
        proposal.withdrawn_at = datetime.now(UTC)
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="proposal_withdrawn",
            target_type="proposal",
            target_id=proposal.id,
            metadata={"project_id": str(project_id)},
        )
        await db.flush()
        await db.refresh(proposal)
    return proposal


async def accept_proposal(
    *,
    db: AsyncSession,
    operator: User,
    project_id: UUID,
    proposal_id: UUID,
) -> Project:
    """Accept one pending Proposal and assign the Project."""
    operator_id = operator.id
    if db.in_transaction():
        await db.rollback()

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
        if project.status != "open":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only open Projects can accept a Proposal.",
            )

        proposal = await db.scalar(
            select(Proposal)
            .where(
                Proposal.id == proposal_id,
                Proposal.project_id == project_id,
            )
            .with_for_update()
        )
        if proposal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proposal not found.",
            )
        if proposal.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only pending Proposals can be accepted.",
            )

        now = datetime.now(UTC)
        proposal.status = "accepted"
        proposal.accepted_at = now
        project.status = "assigned"
        project.accepted_proposal_id = proposal.id
        project.milestone_plan_status = "draft"
        await db.execute(
            update(Proposal)
            .where(
                Proposal.project_id == project_id,
                Proposal.id != proposal.id,
                Proposal.status == "pending",
            )
            .values(status="rejected")
        )
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="proposal_accepted",
            target_type="proposal",
            target_id=proposal.id,
            metadata={
                "project_id": str(project.id),
                "contributor_id": str(proposal.contributor_id),
            },
        )
        await db.flush()
        await db.refresh(project)
    return project
