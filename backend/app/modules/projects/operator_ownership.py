"""Project operator-resolution helpers.

This module centralizes the additive user-or-organization operator branch used
by org-operated Project features without changing existing individual flows. It
mirrors the seller-resolution pattern used for org-owned Frameworks so every
project read path that asks "who operates this Project" resolves the same
descriptor regardless of ownership branch.

Maps to: Task 6 in docs/superpowers/specs/2026-07-10-org-operator-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project, Proposal


@dataclass(frozen=True)
class ProjectOperator:
    """Resolved operator identity for one Project.

    Attributes:
        kind: ``"user"`` for an individually-operated Project, ``"org"`` for an
            organization-operated Project.
        user_id: The operating User's id when ``kind == "user"``, else ``None``.
        org_id: The operating Organization's id when ``kind == "org"``, else
            ``None``.
    """

    kind: Literal["user", "org"]
    user_id: UUID | None
    org_id: UUID | None


def resolve_project_operator(project: Project) -> ProjectOperator:
    """Return the effective operator branch for one Project row.

    Args:
        project: The Project whose operator identity to resolve.

    Returns:
        A :class:`ProjectOperator` describing the individual or organization
        operator for the Project.
    """
    if project.operator_org_id is not None:
        return ProjectOperator(
            kind="org",
            user_id=None,
            org_id=project.operator_org_id,
        )
    return ProjectOperator(kind="user", user_id=project.operator_id, org_id=None)


async def resolve_operator_recipient_user_ids(
    db: AsyncSession, *, project: Project
) -> list[UUID]:
    """Return the user ids that act on a Project's Operator side.

    For an individually-operated Project this is the single Operator. For an
    organization-operated Project it is every owner/admin of the operating
    organization, who collectively hold the Operator role. Returns an empty list
    when no recipient resolves so a notification never dispatches with a null id.

    Args:
        db: Async SQLAlchemy session.
        project: The Project whose Operator-side recipients to resolve.

    Returns:
        The Operator-side user ids for the Project.
    """
    operator = resolve_project_operator(project)
    if operator.kind == "user":
        return [operator.user_id] if operator.user_id is not None else []

    # Local import avoids a circular import: organizations imports project models.
    from app.modules.organizations.models import OrgMember

    rows = await db.scalars(
        select(OrgMember.user_id).where(
            OrgMember.org_id == operator.org_id,
            OrgMember.role.in_(("owner", "admin")),
        )
    )
    return list(rows.all())


async def user_is_project_member(
    db: AsyncSession,
    *,
    project: Project,
    proposal: Proposal,
    user_id: UUID,
) -> bool:
    """Return whether a user belongs to a Project workspace.

    Admits the accepted-Contributor-side user (the individual Contributor or the
    staffed delivering member for an org Proposal) and the Operator side (the
    individual Operator, or any owner/admin of the operating organization). A
    NULL ``operator_id`` on an org-operated Project can never match an
    authenticated user id, so org admins are admitted only via org membership.

    Args:
        db: Async SQLAlchemy session.
        project: The Project whose workspace membership is checked.
        proposal: The accepted Proposal for the Project.
        user_id: The candidate member's user id.

    Returns:
        ``True`` when the user may act inside the Project workspace.
    """
    # Local import avoids a circular import through the workspace helper module.
    from app.modules.projects.workspace import workspace_contributor_user_id

    workspace_user_id = await workspace_contributor_user_id(db, proposal=proposal)
    if user_id == workspace_user_id:
        return True
    return user_id in set(
        await resolve_operator_recipient_user_ids(db, project=project)
    )
