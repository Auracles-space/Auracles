"""Shared workspace membership resolution for Project proposals.

Resolves the user currently authorized to act on the accepted-Contributor side
of a Project workspace: the individual Contributor for user-owned Proposals, or
the staffed delivering member for organization-owned Proposals. Centralizes the
XOR-aware lookup so every workspace guard and notification path admits the same
participant.

Maps to: FR-PROJ workspace access under org contributor ownership.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Proposal


async def workspace_contributor_user_id(
    db: AsyncSession,
    *,
    proposal: Proposal,
) -> UUID | None:
    """Return the user id representing the accepted-Contributor side, if any.

    For user-owned Proposals this is ``contributor_id``. For organization-owned
    Proposals it is the user backing the staffed ``delivering_member_id``. Returns
    ``None`` when an org Proposal has no live staffed member (member removed).

    Args:
        db: Async SQLAlchemy session.
        proposal: The Proposal whose workspace participant to resolve.

    Returns:
        The representing user's UUID, or ``None`` if unresolved.
    """
    if proposal.contributor_id is not None:
        return proposal.contributor_id
    if proposal.contributor_org_id is None or proposal.delivering_member_id is None:
        return None

    # Local import avoids a circular dependency: organizations imports project models.
    from app.modules.organizations.models import OrgMember

    return cast(
        "UUID | None",
        await db.scalar(
            select(OrgMember.user_id)
            .where(
                OrgMember.id == proposal.delivering_member_id,
                OrgMember.org_id == proposal.contributor_org_id,
            )
            .limit(1)
        ),
    )
