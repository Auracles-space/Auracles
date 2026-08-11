"""Project and Proposal orchestration services.

Slice 4 covers the marketplace workflow up to assignment: Operators create and
manage open Projects, Contributors submit Proposals, and Operators accept one
Proposal to move the Project into the assigned state.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.currency import platform_currency
from app.modules.auth.models import User
from app.modules.projects import notifications as project_notifications
from app.modules.projects.models import (
    Milestone,
    Project,
    Proposal,
    ProposalAmendment,
)
from app.modules.projects.operator_ownership import (
    ProjectOperator,
    resolve_operator_recipient_user_ids,
    user_is_project_member,
)
from app.modules.projects.schemas import (
    AmendmentCreateRequest,
    DeliverableSpec,
    OrgDeliveryResponse,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectsResponse,
    ProjectUpdateRequest,
    ProposalCreateRequest,
    ProposalResponse,
    ProposalsResponse,
)
from app.modules.projects.workspace import workspace_contributor_user_id
from app.modules.workspace.models import WorkspaceMessage

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
    return select(Project).where(Project.deleted_at.is_(None))


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


def _proposal_snapshot(proposal: Proposal) -> dict[str, Any]:
    """Return the amendment-controlled Proposal fields as JSONB-safe values."""
    return {
        "scope": proposal.scope,
        "budget": f"{proposal.budget:.2f}",
        "timeline_days": proposal.timeline_days,
    }


def _normalize_amendment_after(
    *,
    change_type: str,
    after: dict[str, Any],
    before: dict[str, Any],
) -> dict[str, Any]:
    """Validate and normalize an amendment's requested Proposal changes."""
    allowed_by_type = {
        "scope": {"scope"},
        "budget": {"budget"},
        "timeline": {"timeline_days"},
        "combo": {"scope", "budget", "timeline_days"},
    }
    allowed_keys = allowed_by_type[change_type]
    if not after or not set(after).issubset(allowed_keys):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Amendment after fields must match change_type '{change_type}'.",
        )

    normalized = dict(before)
    if "scope" in after:
        scope = str(after["scope"]).strip()
        if len(scope) < 10:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Amended scope must be at least 10 characters.",
            )
        normalized["scope"] = scope
    if "budget" in after:
        try:
            budget = Decimal(str(after["budget"]))
        except InvalidOperation as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Amended budget must be a decimal amount.",
            ) from exc
        if budget <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Amended budget must be positive.",
            )
        normalized["budget"] = f"{budget.quantize(Decimal('0.01'))}"
    if "timeline_days" in after:
        try:
            timeline_days = int(after["timeline_days"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Amended timeline_days must be an integer.",
            ) from exc
        if timeline_days <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Amended timeline_days must be positive.",
            )
        normalized["timeline_days"] = timeline_days
    if normalized == before:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Amendment must change at least one Proposal field.",
        )
    return normalized


async def _project_operator_recipient_ids(
    db: AsyncSession, project: Project
) -> list[UUID]:
    """Resolve the user recipients for Operator-facing Project notifications.

    For an individually-operated Project this is the single Operator. For an
    organization-operated Project it is the organization's owner and admins,
    who act on the Operator side. Returns an empty list when no recipient can
    be resolved so a notification is never dispatched with a null user id.
    """
    return await resolve_operator_recipient_user_ids(db, project=project)


async def _is_project_member(
    db: AsyncSession, project: Project, proposal: Proposal, user_id: UUID
) -> bool:
    """Return whether a user is the Project Operator or accepted Contributor side.

    The Operator side resolves to the individual Operator or, for an
    organization-operated Project, any owner/admin of the operating org. A NULL
    ``operator_id`` on an org-operated Project can never match an authenticated
    (non-null) ``user_id``.
    """
    return await user_is_project_member(
        db, project=project, proposal=proposal, user_id=user_id
    )


async def _is_counterparty(
    db: AsyncSession,
    project: Project,
    proposal: Proposal,
    actor_id: UUID,
    proposed_by: UUID,
) -> bool:
    """Return whether actor is the other Project party for an amendment."""
    return (
        await _is_project_member(db, project, proposal, actor_id)
        and actor_id != proposed_by
    )


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


async def _insert_project(
    *,
    db: AsyncSession,
    operator: ProjectOperator,
    actor_id: UUID,
    posting_member_id: UUID | None,
    payload: ProjectCreateRequest,
) -> Project:
    """Create an open Project for a resolved operator inside a new transaction.

    Threads the individual-or-organization operator descriptor through a single
    create path so the active-project cap, audit trail, and Project row are
    enforced identically for both ownership branches. Serializes concurrent
    creates per account by locking the operating User or Organization row.

    Args:
        db: Async SQLAlchemy session with no open transaction.
        operator: The resolved individual or organization operator.
        actor_id: The acting user id recorded on the audit entry.
        posting_member_id: The org member who posted an org-operated Project,
            or ``None`` for an individually-operated Project.
        payload: Validated Project create request body.

    Returns:
        The persisted open Project.

    Raises:
        HTTPException(409): If the operator already has 5 active Projects.
    """
    now = datetime.now(UTC)
    async with db.begin():
        if operator.kind == "org":
            # Local import avoids a circular import: organizations imports
            # project models at module load.
            from app.modules.organizations.models import Organization

            await db.scalar(
                select(Organization)
                .where(Organization.id == operator.org_id)
                .with_for_update()
            )
            active_count = await db.scalar(
                select(func.count(Project.id)).where(
                    Project.operator_org_id == operator.org_id,
                    Project.status.in_(ACTIVE_PROJECT_STATUSES),
                    Project.deleted_at.is_(None),
                )
            )
        else:
            # Lock the Operator row so concurrent creates serialize per account.
            await db.scalar(
                select(User).where(User.id == operator.user_id).with_for_update()
            )
            active_count = await db.scalar(
                select(func.count(Project.id)).where(
                    Project.operator_id == operator.user_id,
                    Project.status.in_(ACTIVE_PROJECT_STATUSES),
                    Project.deleted_at.is_(None),
                )
            )
        if int(active_count or 0) >= MAX_ACTIVE_PROJECTS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Operator has reached the maximum of 5 active Projects.",
            )

        project = Project(
            operator_id=operator.user_id,
            operator_org_id=operator.org_id,
            posting_member_id=posting_member_id,
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
            actor_id=actor_id,
            action="project_created",
            target_type="project",
            target_id=project.id,
            metadata={"title": project.title},
        )
        await db.flush()
        await db.refresh(project)
    return project


async def create_project(
    *,
    db: AsyncSession,
    operator: User,
    payload: ProjectCreateRequest,
) -> Project:
    """Create an open Project while enforcing the MVP active-project cap."""
    # Capture the operator id before any rollback expires the ORM instance.
    operator_id = operator.id
    if db.in_transaction():
        await db.rollback()

    return await _insert_project(
        db=db,
        operator=ProjectOperator(kind="user", user_id=operator_id, org_id=None),
        actor_id=operator_id,
        posting_member_id=None,
        payload=payload,
    )


async def create_org_project(
    *,
    db: AsyncSession,
    org_id: UUID,
    actor: User,
    posting_member_id: UUID,
    payload: ProjectCreateRequest,
) -> ProjectResponse:
    """Create an open Project operated by an organization.

    Stamps ``operator_org_id`` and the posting member, leaving ``operator_id``
    NULL, so the org XOR operator branch owns the Project. Requires the org
    Operator capability to be active (BR-ORG operator gate).

    Args:
        db: Async SQLAlchemy session.
        org_id: The operating organization's id.
        actor: The acting admin/owner user (recorded on the audit entry).
        posting_member_id: The acting caller's OrgMember id (internal
            provenance, never exposed in responses).
        payload: Validated Project create request body.

    Returns:
        The persisted Project as a response carrying the Organization name.

    Raises:
        HTTPException(403): If the org Operator capability is not active.
        HTTPException(409): If the org already has 5 active Projects.
    """
    from app.modules.organizations.models import Organization
    from app.modules.organizations.operator_service import operator_capability_active

    # Capture the acting user id before any rollback expires the ORM instance.
    actor_id = actor.id
    if not await operator_capability_active(db, org_id=org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "capability_suspended"},
        )
    if db.in_transaction():
        await db.rollback()

    project = await _insert_project(
        db=db,
        operator=ProjectOperator(kind="org", user_id=None, org_id=org_id),
        actor_id=actor_id,
        posting_member_id=posting_member_id,
        payload=payload,
    )
    org_name = await db.scalar(
        select(Organization.name).where(Organization.id == org_id)
    )
    return _project_with_operator_name(project, org_name)


async def list_org_projects(
    *,
    db: AsyncSession,
    org_id: UUID,
    org_name: str,
    page: int,
    page_size: int,
) -> ProjectsResponse:
    """List Projects operated by one organization for its owners and admins.

    Args:
        db: Async SQLAlchemy session.
        org_id: The operating organization's id.
        org_name: The organization name surfaced as ``operator_name``.
        page: 1-indexed page number.
        page_size: Page size.

    Returns:
        A paginated response of the organization's operated Projects.
    """
    query = _project_query().where(Project.operator_org_id == org_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = await db.execute(
        query.order_by(Project.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    projects = [
        _project_with_operator_name(project, org_name)
        for project in rows.scalars()
    ]
    return ProjectsResponse(
        projects=projects,
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


async def get_org_project(
    *,
    db: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    org_name: str,
) -> ProjectResponse:
    """Return one Project operated by an organization or conceal it as missing."""
    project = await db.scalar(
        _project_query().where(
            Project.id == project_id,
            Project.operator_org_id == org_id,
        )
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    return _project_with_operator_name(project, org_name)


def _project_with_operator_name(
    project: Project, operator_name: str | None
) -> ProjectResponse:
    """Build a ProjectResponse carrying the posting Operator's display name."""
    response = ProjectResponse.model_validate(project)
    response.operator_name = operator_name
    return response


async def list_projects(
    *,
    db: AsyncSession,
    user: User,
    role: Literal["contributor", "operator"],
    token_roles: list[str],
    page: int,
    page_size: int,
    scope: Literal["open", "assigned"] = "open",
) -> ProjectsResponse:
    """List Projects for a role.

    For Contributors, ``scope`` selects the open marketplace feed
    (``scope="open"``) or the Projects the Contributor has been assigned via an
    accepted Proposal (``scope="assigned"``). ``scope`` is ignored for
    Operators, who always see the Projects they own.
    """
    if role not in token_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requested Project role is not present in token.",
        )

    query = _project_query()
    if role == "contributor":
        if scope == "assigned":
            # Projects this Contributor was assigned via an accepted Proposal —
            # these have left the open feed (status moved to 'assigned'), so the
            # open filter alone would hide their own active work.
            query = query.where(
                Project.id.in_(
                    select(Proposal.project_id).where(
                        Proposal.contributor_id == user.id,
                        Proposal.status == "accepted",
                    )
                )
            )
        else:
            query = query.where(Project.status == "open")
    else:
        query = query.where(Project.operator_id == user.id)

    # Local import avoids a circular import: organizations imports project models.
    from app.modules.organizations.models import Organization

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    # Outer-join both operator branches so org-operated Projects (NULL
    # operator_id) still appear in the Contributor feed, with the operator name
    # resolved to the User display name or the Organization name.
    rows = await db.execute(
        query.add_columns(User.display_name, Organization.name)
        .outerjoin(User, User.id == Project.operator_id)
        .outerjoin(Organization, Organization.id == Project.operator_org_id)
        .order_by(Project.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    projects = [
        _project_with_operator_name(
            project, user_name if user_name is not None else org_name
        )
        for project, user_name, org_name in rows.all()
    ]
    return ProjectsResponse(
        projects=projects,
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
            .where(
                Project.id == project_id,
                Project.operator_id == operator_id,
                Project.deleted_at.is_(None),
            )
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


async def _delete_project(
    *,
    db: AsyncSession,
    actor_id: UUID,
    project_id: UUID,
    operator_org_id: UUID | None,
) -> None:
    """Soft-delete one uncommenced Project for either Operator identity."""
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project_query = select(Project).where(
            Project.id == project_id,
            Project.deleted_at.is_(None),
        )
        if operator_org_id is None:
            project_query = project_query.where(Project.operator_id == actor_id)
        else:
            project_query = project_query.where(
                Project.operator_org_id == operator_org_id
            )
        project = await db.scalar(project_query.with_for_update())
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found.",
            )
        if project.status != "open":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only uncommenced open Projects can be deleted.",
            )
        pending_proposal_id = await db.scalar(
            select(Proposal.id)
            .where(
                Proposal.project_id == project.id,
                Proposal.status == "pending",
            )
            .limit(1)
        )
        if pending_proposal_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Resolve every pending Proposal before deleting this Project.",
            )
        project.deleted_at = datetime.now(UTC)
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="project_deleted",
            target_type="project",
            target_id=project.id,
            metadata={
                "operator_kind": "org" if operator_org_id is not None else "user",
                "operator_org_id": (
                    str(operator_org_id) if operator_org_id is not None else None
                ),
            },
        )

    logger.bind(
        module="projects",
        action="delete_project",
        user_id=actor_id,
        project_id=project_id,
        operator_org_id=operator_org_id,
    ).info("project_deleted")


async def delete_project(
    *,
    db: AsyncSession,
    operator: User,
    project_id: UUID,
) -> None:
    """Soft-delete an uncommenced Project owned by an individual Operator."""
    await _delete_project(
        db=db,
        actor_id=operator.id,
        project_id=project_id,
        operator_org_id=None,
    )


async def delete_org_project(
    *,
    db: AsyncSession,
    org_id: UUID,
    actor_id: UUID,
    project_id: UUID,
) -> None:
    """Soft-delete an uncommenced Project owned by an organization."""
    await _delete_project(
        db=db,
        actor_id=actor_id,
        project_id=project_id,
        operator_org_id=org_id,
    )


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
            select(Project)
            .where(Project.id == project_id, Project.deleted_at.is_(None))
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

    # Fanout runs after commit so the Operator only hears about a durable bid.
    for recipient_id in await _project_operator_recipient_ids(db, project):
        project_notifications.notify_proposal_submitted(
            operator_id=recipient_id,
            proposal=proposal,
            operator_org_id=project.operator_org_id,
        )
    return proposal


async def submit_org_proposal(
    *,
    db: AsyncSession,
    org_id: UUID,
    actor_id: UUID,
    project_id: UUID,
    delivering_member_id: UUID,
    scope: str,
    budget: Decimal,
    timeline_days: int,
    deliverables: list[dict[str, str]],
) -> Proposal:
    """Submit an organization-owned Proposal against an open Project."""
    from app.modules.organizations.contributor_service import (
        contributor_capability_active,
    )
    from app.modules.organizations.models import OrgMember

    if not await contributor_capability_active(db, org_id=org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "capability_suspended"},
        )
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
        # Org-level self-deal: an organization's Contributor arm cannot bid on a
        # Project its own Operator arm posted.
        if project.operator_org_id == org_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "self_deal_conflict"},
            )
        # Member-level self-deal: the individual Operator is a member of the
        # bidding organization.
        self_deal = await db.scalar(
            select(OrgMember.id)
            .where(
                OrgMember.org_id == org_id,
                OrgMember.user_id == project.operator_id,
            )
            .limit(1)
        )
        if self_deal is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "self_deal_conflict"},
            )

        staffed_member = await db.scalar(
            select(OrgMember).where(
                OrgMember.id == delivering_member_id,
                OrgMember.org_id == org_id,
            )
        )
        if staffed_member is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "delivering_member_invalid"},
            )
        existing = await db.scalar(
            select(Proposal.id)
            .where(
                Proposal.project_id == project_id,
                Proposal.contributor_org_id == org_id,
                Proposal.status.in_(("pending", "accepted")),
            )
            .limit(1)
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Organization already has an active Proposal for this Project.",
            )

        proposal = Proposal(
            project_id=project_id,
            contributor_id=None,
            contributor_org_id=org_id,
            delivering_member_id=delivering_member_id,
            scope=scope,
            budget=budget,
            currency=platform_currency(),
            timeline_days=timeline_days,
            deliverables=deliverables,
        )
        db.add(proposal)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="proposal_submitted",
            target_type="proposal",
            target_id=proposal.id,
            metadata={"project_id": str(project_id), "org_id": str(org_id)},
        )
        await db.flush()
        await db.refresh(proposal)

    for recipient_id in await _project_operator_recipient_ids(db, project):
        project_notifications.notify_proposal_submitted(
            operator_id=recipient_id,
            proposal=proposal,
            operator_org_id=project.operator_org_id,
        )
    return proposal


async def reassign_delivering_member(
    *,
    db: AsyncSession,
    org_id: UUID,
    actor_id: UUID,
    proposal_id: UUID,
    delivering_member_id: UUID,
) -> Proposal:
    """Reassign the staffed org member for accepted work before funding starts."""
    from app.modules.organizations.models import OrgMember

    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        proposal = await db.scalar(
            select(Proposal)
            .where(
                Proposal.id == proposal_id,
                Proposal.contributor_org_id == org_id,
            )
            .with_for_update()
        )
        if proposal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proposal not found.",
            )
        if proposal.status != "accepted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only accepted Proposals can be reassigned.",
            )

        staffed_member = await db.scalar(
            select(OrgMember).where(
                OrgMember.id == delivering_member_id,
                OrgMember.org_id == org_id,
            )
        )
        if staffed_member is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "delivering_member_invalid"},
            )

        started_work = await db.scalar(
            select(Milestone.id)
            .where(
                Milestone.project_id == proposal.project_id,
                Milestone.status != "pending",
            )
            .limit(1)
        )
        if started_work is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Started delivery cannot be reassigned.",
            )

        proposal.delivering_member_id = delivering_member_id
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="proposal_delivering_member_reassigned",
            target_type="proposal",
            target_id=proposal.id,
            metadata={"delivering_member_id": str(delivering_member_id)},
        )
        await db.flush()
        await db.refresh(proposal)
    return proposal


async def withdraw_org_proposal(
    *,
    db: AsyncSession,
    org_id: UUID,
    actor_id: UUID,
    proposal_id: UUID,
) -> Proposal:
    """Withdraw one pending organization-owned Proposal."""
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        proposal = await db.scalar(
            select(Proposal)
            .where(
                Proposal.id == proposal_id,
                Proposal.contributor_org_id == org_id,
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
            actor_id=actor_id,
            action="proposal_withdrawn",
            target_type="proposal",
            target_id=proposal.id,
            metadata={"project_id": str(proposal.project_id), "org_id": str(org_id)},
        )
        operator_id = await db.scalar(
            select(Project.operator_id).where(Project.id == proposal.project_id)
        )
        await db.flush()
        await db.refresh(proposal)

    if operator_id is not None:
        project_notifications.notify_proposal_withdrawn(
            operator_id=operator_id,
            project_id=proposal.project_id,
            proposal_id=proposal.id,
        )
    return proposal


def _proposal_with_name(
    proposal: Proposal, contributor_name: str | None
) -> ProposalResponse:
    """Build a ProposalResponse carrying the proposer's display name."""
    response = ProposalResponse.model_validate(proposal)
    response.contributor_name = contributor_name
    return response


async def _proposal_workspace_user_id(db: AsyncSession, proposal: Proposal) -> UUID:
    """Resolve the user currently representing the Proposal in the workspace."""
    user_id = await workspace_contributor_user_id(db, proposal=proposal)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Accepted Proposal is missing its staffed delivery member.",
        )
    return user_id


async def list_org_proposals(
    *,
    db: AsyncSession,
    org_id: UUID,
    org_name: str,
) -> ProposalsResponse:
    """List Proposals submitted under one organization identity."""
    rows = await db.execute(
        select(Proposal)
        .where(Proposal.contributor_org_id == org_id)
        .order_by(Proposal.created_at.desc())
    )
    return ProposalsResponse(
        proposals=[
            _proposal_with_name(proposal, org_name) for proposal in rows.scalars()
        ]
    )


async def list_org_deliveries(
    *,
    db: AsyncSession,
    org_id: UUID,
    member_id: UUID,
    member_role: str,
) -> list[OrgDeliveryResponse]:
    """List accepted Project workspaces for one organization view."""
    query = (
        select(Proposal, Project)
        .join(Project, Project.id == Proposal.project_id)
        .where(
            Proposal.contributor_org_id == org_id,
            Proposal.status == "accepted",
            Project.status.in_(("assigned", "in_progress", "delivered", "disputed")),
        )
        .order_by(Proposal.accepted_at.desc().nullslast(), Proposal.created_at.desc())
    )
    if member_role == "member":
        query = query.where(Proposal.delivering_member_id == member_id)

    rows = await db.execute(query)
    return [
        OrgDeliveryResponse(
            proposal_id=proposal.id,
            project_id=project.id,
            project_title=project.title,
            project_status=project.status,
            milestone_plan_status=project.milestone_plan_status,
            delivering_member_id=proposal.delivering_member_id,
            accepted_at=proposal.accepted_at,
            created_at=proposal.created_at,
        )
        for proposal, project in rows.all()
    ]


async def list_project_proposals(
    *,
    db: AsyncSession,
    operator: User,
    project_id: UUID,
) -> ProposalsResponse:
    """List Proposals for an Operator-owned Project, with proposer names."""
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
    rows = await db.execute(
        select(Proposal, User.display_name)
        .join(User, User.id == Proposal.contributor_id)
        .where(Proposal.project_id == project_id)
        .order_by(Proposal.created_at.desc())
    )
    proposals = [_proposal_with_name(proposal, name) for proposal, name in rows.all()]
    return ProposalsResponse(proposals=proposals)


async def list_org_project_proposals(
    *,
    db: AsyncSession,
    org_id: UUID,
    project_id: UUID,
) -> ProposalsResponse:
    """List proposals submitted to one organization-operated Project."""
    from app.modules.organizations.models import Organization

    project = await db.scalar(
        select(Project.id).where(
            Project.id == project_id,
            Project.operator_org_id == org_id,
        )
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    rows = await db.execute(
        select(Proposal, User.display_name, Organization.name)
        .outerjoin(User, User.id == Proposal.contributor_id)
        .outerjoin(Organization, Organization.id == Proposal.contributor_org_id)
        .where(Proposal.project_id == project_id)
        .order_by(Proposal.created_at.desc())
    )
    return ProposalsResponse(
        proposals=[
            _proposal_with_name(proposal, user_name or org_name)
            for proposal, user_name, org_name in rows.all()
        ]
    )


async def list_my_project_proposals(
    *,
    db: AsyncSession,
    contributor: User,
    project_id: UUID,
) -> ProposalsResponse:
    """List the current Contributor's Proposals for one Project, with name."""
    rows = await db.execute(
        select(Proposal, User.display_name)
        .join(User, User.id == Proposal.contributor_id)
        .where(
            Proposal.project_id == project_id,
            Proposal.contributor_id == contributor.id,
        )
        .order_by(Proposal.created_at.desc())
    )
    proposals = [_proposal_with_name(proposal, name) for proposal, name in rows.all()]
    return ProposalsResponse(proposals=proposals)


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
        withdrawn_operator_id = await db.scalar(
            select(Project.operator_id).where(Project.id == project_id)
        )
        await db.flush()
        await db.refresh(proposal)

    if withdrawn_operator_id is not None:
        project_notifications.notify_proposal_withdrawn(
            operator_id=withdrawn_operator_id,
            project_id=project_id,
            proposal_id=proposal.id,
        )
    return proposal


async def _cancel_acceptance(
    *,
    db: AsyncSession,
    actor_id: UUID,
    project_id: UUID,
    operator_org_id: UUID | None,
) -> Project:
    """Cancel one acceptance for an individual member or operating org."""
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project_query = select(Project).where(Project.id == project_id)
        if operator_org_id is not None:
            project_query = project_query.where(
                Project.operator_org_id == operator_org_id
            )
        project = await db.scalar(project_query.with_for_update())
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found.",
            )
        if project.status != "assigned" or project.accepted_proposal_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Only an assigned, unfunded Project acceptance can be cancelled."
                ),
            )
        proposal = await db.scalar(
            select(Proposal)
            .where(Proposal.id == project.accepted_proposal_id)
            .with_for_update()
        )
        if proposal is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Accepted Proposal is not available.",
            )
        workspace_user_id = await workspace_contributor_user_id(db, proposal=proposal)
        acting_as_org_operator = operator_org_id is not None
        if not acting_as_org_operator and actor_id not in {
            project.operator_id,
            workspace_user_id,
        }:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Project members can cancel the acceptance.",
            )

        now = datetime.now(UTC)
        if not acting_as_org_operator and actor_id == workspace_user_id:
            proposal.status = "withdrawn"
            proposal.withdrawn_at = now
        else:
            proposal.status = "rejected"
        proposal.accepted_at = None

        await db.execute(delete(Milestone).where(Milestone.project_id == project.id))
        project.status = "open"
        project.accepted_proposal_id = None
        project.milestone_plan_status = "draft"

        await write_audit(
            db=db,
            actor_id=actor_id,
            action="proposal_acceptance_cancelled",
            target_type="project",
            target_id=project.id,
            metadata={
                "proposal_id": str(proposal.id),
                "proposal_status": proposal.status,
                "operator_org_id": (
                    str(operator_org_id) if operator_org_id is not None else None
                ),
            },
        )
        await db.flush()
        await db.refresh(project)
    return project


async def cancel_acceptance(
    *,
    db: AsyncSession,
    user: User,
    project_id: UUID,
) -> Project:
    """Cancel an unfunded acceptance as an individual Project member."""
    return await _cancel_acceptance(
        db=db,
        actor_id=user.id,
        project_id=project_id,
        operator_org_id=None,
    )


async def cancel_org_acceptance(
    *,
    db: AsyncSession,
    org_id: UUID,
    actor_id: UUID,
    project_id: UUID,
) -> Project:
    """Cancel an unfunded acceptance as the operating organization."""
    return await _cancel_acceptance(
        db=db,
        actor_id=actor_id,
        project_id=project_id,
        operator_org_id=org_id,
    )


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
        # Capture the losing bidders before the bulk reject so each can be
        # notified of the outcome after commit.
        rejected_proposals = (
            await db.execute(
                select(Proposal).where(
                    Proposal.project_id == project_id,
                    Proposal.id != proposal.id,
                    Proposal.status == "pending",
                )
            )
        ).scalars().all()
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
                "contributor_id": (
                    str(proposal.contributor_id)
                    if proposal.contributor_id is not None
                    else None
                ),
                "contributor_org_id": (
                    str(proposal.contributor_org_id)
                    if proposal.contributor_org_id is not None
                    else None
                ),
            },
        )
        accepted_contributor_id = await _proposal_workspace_user_id(db, proposal)
        await db.flush()
        await db.refresh(project)

    project_notifications.notify_proposal_accepted(
        contributor_id=accepted_contributor_id,
        proposal=proposal,
    )
    for rejected_proposal in rejected_proposals:
        rejected_contributor_id = await _proposal_workspace_user_id(
            db, rejected_proposal
        )
        project_notifications.notify_proposal_rejected(
            contributor_id=rejected_contributor_id,
            project_id=project_id,
            proposal_id=rejected_proposal.id,
        )
    return project


async def accept_org_proposal(
    *,
    db: AsyncSession,
    org_id: UUID,
    actor_id: UUID,
    project_id: UUID,
    proposal_id: UUID,
) -> Project:
    """Accept one pending Proposal for an organization-operated Project.

    Mirrors :func:`accept_proposal` for the org Operator branch: the Project is
    matched on ``operator_org_id`` rather than ``operator_id`` (a NULL
    ``operator_id`` on an org Project can never match an individual user), and
    the acting org admin is recorded as the audit actor. Requires the org
    Operator capability to be active so a suspended org cannot advance the money
    path.

    Args:
        db: Async SQLAlchemy session.
        org_id: The operating organization's id (from the resolved org context).
        actor_id: The acting org owner/admin user id (audit actor).
        project_id: The org-operated Project accepting a Proposal.
        proposal_id: The pending Proposal to accept.

    Returns:
        The assigned Project.

    Raises:
        HTTPException(403): If the org Operator capability is not active.
        HTTPException(404): If the Project or Proposal is not found for this org.
        HTTPException(409): If the Project is not open or the Proposal not pending.
    """
    from app.modules.organizations.operator_service import operator_capability_active

    if not await operator_capability_active(db, org_id=org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "capability_suspended"},
        )
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project = await db.scalar(
            select(Project)
            .where(Project.id == project_id, Project.operator_org_id == org_id)
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
        rejected_proposals = (
            await db.execute(
                select(Proposal).where(
                    Proposal.project_id == project_id,
                    Proposal.id != proposal.id,
                    Proposal.status == "pending",
                )
            )
        ).scalars().all()
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
            actor_id=actor_id,
            action="proposal_accepted",
            target_type="proposal",
            target_id=proposal.id,
            metadata={
                "project_id": str(project.id),
                "operator_org_id": str(org_id),
                "contributor_id": (
                    str(proposal.contributor_id)
                    if proposal.contributor_id is not None
                    else None
                ),
                "contributor_org_id": (
                    str(proposal.contributor_org_id)
                    if proposal.contributor_org_id is not None
                    else None
                ),
            },
        )
        accepted_contributor_id = await _proposal_workspace_user_id(db, proposal)
        await db.flush()
        await db.refresh(project)

    project_notifications.notify_proposal_accepted(
        contributor_id=accepted_contributor_id,
        proposal=proposal,
    )
    for rejected_proposal in rejected_proposals:
        rejected_contributor_id = await _proposal_workspace_user_id(
            db, rejected_proposal
        )
        project_notifications.notify_proposal_rejected(
            contributor_id=rejected_contributor_id,
            project_id=project_id,
            proposal_id=rejected_proposal.id,
        )
    return project


async def propose_amendment(
    *,
    db: AsyncSession,
    actor: User,
    project_id: UUID,
    proposal_id: UUID,
    payload: AmendmentCreateRequest,
) -> ProposalAmendment:
    """Create a pending Proposal amendment from one accepted Project member."""
    actor_id = actor.id
    if db.in_transaction():
        await db.rollback()

    now = datetime.now(UTC)
    async with db.begin():
        project = await db.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        proposal = await db.scalar(
            select(Proposal)
            .where(Proposal.id == proposal_id, Proposal.project_id == project_id)
            .with_for_update()
        )
        if project is None or proposal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project or Proposal not found.",
            )
        if project.accepted_proposal_id != proposal.id or proposal.status != "accepted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Amendments require an accepted Proposal.",
            )
        if not await _is_project_member(db, project, proposal, actor_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Project members can propose amendments.",
            )

        existing = await db.scalar(
            select(ProposalAmendment)
            .where(
                ProposalAmendment.proposal_id == proposal.id,
                ProposalAmendment.status == "pending",
            )
            .with_for_update()
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This Proposal already has a pending amendment.",
            )

        before = _proposal_snapshot(proposal)
        after = _normalize_amendment_after(
            change_type=payload.change_type,
            after=payload.after,
            before=before,
        )
        amendment = ProposalAmendment(
            proposal_id=proposal.id,
            proposed_by=actor_id,
            change_type=payload.change_type,
            before=before,
            after=after,
            reason=payload.reason,
            expires_at=now + timedelta(days=7),
        )
        db.add(amendment)
        await db.flush()
        db.add(
            _workspace_system_message(
                project_id=project.id,
                system_event="amendment_proposed",
                payload={
                    "amendment_id": str(amendment.id),
                    "proposal_id": str(proposal.id),
                    "proposed_by": str(actor_id),
                    "change_type": amendment.change_type,
                },
            )
        )
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="amendment_proposed",
            target_type="proposal_amendment",
            target_id=amendment.id,
            metadata={"project_id": str(project.id), "proposal_id": str(proposal.id)},
        )
        # The counterparty is the accepted member who did not propose the change.
        # Amendments require an accepted Proposal, which today only exists on
        # individually-operated Projects (org acceptance lands in Task 7), so the
        # Operator id is always set on the non-operator branch here.
        if actor_id == project.operator_id:
            counterparty_id = await _proposal_workspace_user_id(db, proposal)
        else:
            assert project.operator_id is not None
            counterparty_id = project.operator_id
        amendment_project_id = project.id
        await db.flush()
        await db.refresh(amendment)

    project_notifications.notify_amendment_proposed(
        counterparty_id=counterparty_id,
        project_id=amendment_project_id,
        proposal_id=proposal_id,
        amendment_id=amendment.id,
    )
    return amendment


async def accept_amendment(
    *,
    db: AsyncSession,
    actor: User,
    project_id: UUID,
    proposal_id: UUID,
    amendment_id: UUID,
) -> ProposalAmendment:
    """Accept a pending amendment as the counterparty and mutate the Proposal."""
    actor_id = actor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project, proposal, amendment = await _load_pending_amendment_for_update(
            db=db,
            project_id=project_id,
            proposal_id=proposal_id,
            amendment_id=amendment_id,
        )
        if not await _is_counterparty(
            db, project, proposal, actor_id, amendment.proposed_by
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the amendment counterparty can accept it.",
            )

        if proposal.scope != amendment.after["scope"]:
            proposal.scope = amendment.after["scope"]
        if f"{proposal.budget:.2f}" != amendment.after["budget"]:
            proposal.budget = Decimal(amendment.after["budget"])
            project.milestone_plan_status = "draft"
        if proposal.timeline_days != amendment.after["timeline_days"]:
            proposal.timeline_days = int(amendment.after["timeline_days"])

        amendment.status = "accepted"
        amendment.responded_at = datetime.now(UTC)
        amendment.responded_by = actor_id
        db.add(
            _workspace_system_message(
                project_id=project.id,
                system_event="amendment_accepted",
                payload={
                    "amendment_id": str(amendment.id),
                    "proposal_id": str(proposal.id),
                    "responded_by": str(actor_id),
                },
            )
        )
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="amendment_accepted",
            target_type="proposal_amendment",
            target_id=amendment.id,
            metadata={"project_id": str(project.id), "proposal_id": str(proposal.id)},
        )
        amendment_proposer_id = amendment.proposed_by
        accepted_project_id = project.id
        await db.flush()
        await db.refresh(amendment)

    project_notifications.notify_amendment_accepted(
        proposer_id=amendment_proposer_id,
        project_id=accepted_project_id,
        proposal_id=proposal_id,
        amendment_id=amendment.id,
    )
    return amendment


async def reject_amendment(
    *,
    db: AsyncSession,
    actor: User,
    project_id: UUID,
    proposal_id: UUID,
    amendment_id: UUID,
) -> ProposalAmendment:
    """Reject a pending amendment as the counterparty."""
    actor_id = actor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project, proposal, amendment = await _load_pending_amendment_for_update(
            db=db,
            project_id=project_id,
            proposal_id=proposal_id,
            amendment_id=amendment_id,
        )
        if not await _is_counterparty(
            db, project, proposal, actor_id, amendment.proposed_by
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the amendment counterparty can reject it.",
            )
        amendment.status = "rejected"
        amendment.responded_at = datetime.now(UTC)
        amendment.responded_by = actor_id
        db.add(
            _workspace_system_message(
                project_id=project.id,
                system_event="amendment_rejected",
                payload={
                    "amendment_id": str(amendment.id),
                    "proposal_id": str(proposal.id),
                    "responded_by": str(actor_id),
                },
            )
        )
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="amendment_rejected",
            target_type="proposal_amendment",
            target_id=amendment.id,
            metadata={"project_id": str(project.id), "proposal_id": str(proposal.id)},
        )
        rejected_proposer_id = amendment.proposed_by
        rejected_project_id = project.id
        await db.flush()
        await db.refresh(amendment)

    project_notifications.notify_amendment_rejected(
        proposer_id=rejected_proposer_id,
        project_id=rejected_project_id,
        proposal_id=proposal_id,
        amendment_id=amendment.id,
    )
    return amendment


async def withdraw_amendment(
    *,
    db: AsyncSession,
    actor: User,
    project_id: UUID,
    proposal_id: UUID,
    amendment_id: UUID,
) -> ProposalAmendment:
    """Withdraw a pending amendment as its proposer."""
    actor_id = actor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        project, proposal, amendment = await _load_pending_amendment_for_update(
            db=db,
            project_id=project_id,
            proposal_id=proposal_id,
            amendment_id=amendment_id,
        )
        if amendment.proposed_by != actor_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the amendment proposer can withdraw it.",
            )
        amendment.status = "withdrawn"
        amendment.responded_at = datetime.now(UTC)
        amendment.responded_by = actor_id
        db.add(
            _workspace_system_message(
                project_id=project.id,
                system_event="amendment_rejected",
                payload={
                    "amendment_id": str(amendment.id),
                    "proposal_id": str(proposal.id),
                    "withdrawn_by": str(actor_id),
                },
            )
        )
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="amendment_withdrawn",
            target_type="proposal_amendment",
            target_id=amendment.id,
            metadata={"project_id": str(project.id), "proposal_id": str(proposal.id)},
        )
        # Notify the counterparty who was awaiting a response, not the proposer.
        # Amendments require an accepted Proposal, which today only exists on
        # individually-operated Projects (org acceptance lands in Task 7), so the
        # Operator id is always set on the non-operator branch here.
        if actor_id == project.operator_id:
            withdraw_counterparty_id = await _proposal_workspace_user_id(
                db, proposal
            )
        else:
            assert project.operator_id is not None
            withdraw_counterparty_id = project.operator_id
        withdrawn_project_id = project.id
        await db.flush()
        await db.refresh(amendment)

    project_notifications.notify_amendment_withdrawn(
        counterparty_id=withdraw_counterparty_id,
        project_id=withdrawn_project_id,
        proposal_id=proposal_id,
        amendment_id=amendment.id,
    )
    return amendment


async def _load_pending_amendment_for_update(
    *,
    db: AsyncSession,
    project_id: UUID,
    proposal_id: UUID,
    amendment_id: UUID,
) -> tuple[Project, Proposal, ProposalAmendment]:
    """Load a pending amendment with its Project and Proposal under row locks."""
    project = await db.scalar(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    proposal = await db.scalar(
        select(Proposal)
        .where(Proposal.id == proposal_id, Proposal.project_id == project_id)
        .with_for_update()
    )
    amendment = await db.scalar(
        select(ProposalAmendment)
        .where(
            ProposalAmendment.id == amendment_id,
            ProposalAmendment.proposal_id == proposal_id,
        )
        .with_for_update()
    )
    if project is None or proposal is None or amendment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Amendment not found.",
        )
    if amendment.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending amendments can be changed.",
        )
    if project.accepted_proposal_id != proposal.id or proposal.status != "accepted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Amendments require an accepted Proposal.",
        )
    return project, proposal, amendment
