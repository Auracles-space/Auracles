"""Organizations Core service layer.

Org CRUD, membership, invitations, teams, capability reads, and the
derived attestor-role sync. RBAC lives in dependencies.py, never here.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.auth.models import User
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgMember,
)
from app.modules.organizations.schemas import OrganizationCreateRequest


async def create_organization(
    *,
    db: AsyncSession,
    user: User,
    payload: OrganizationCreateRequest,
) -> Organization:
    """Create an organization and seed the creator as its owner.

    Args:
        db: Async database session.
        user: Authenticated creator of the organization.
        payload: Normalized organization creation payload.

    Returns:
        The created organization row.

    Raises:
        HTTPException(409): If the slug is already in use.
    """
    user_id = user.id
    if db.in_transaction():
        await db.rollback()

    organization = Organization(
        slug=payload.slug,
        name=payload.name,
        country=payload.country,
        website=payload.website,
        description=payload.description,
        created_by=user_id,
    )

    try:
        async with db.begin():
            db.add(organization)
            await db.flush()
            db.add(
                OrgMember(
                    org_id=organization.id,
                    user_id=user_id,
                    role="owner",
                )
            )
            await write_audit(
                db=db,
                actor_id=user_id,
                action="org_created",
                target_type="organization",
                target_id=organization.id,
                metadata={"slug": organization.slug},
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization slug already exists.",
        ) from exc

    await db.refresh(organization)
    logger.bind(
        module="organizations",
        action="create_organization",
        user_id=user_id,
        org_id=organization.id,
    ).info("organization_created")
    return organization


async def list_my_organizations(
    *,
    db: AsyncSession,
    user_id: UUID,
) -> list[tuple[Organization, str, list[OrgCapability]]]:
    """Return organizations, my role, and capability rows for one user.

    Args:
        db: Async database session.
        user_id: Authenticated user whose memberships should be listed.

    Returns:
        A list of tuples containing the organization, the user's role, and
        the organization's capability rows.
    """
    memberships = (
        await db.execute(
            select(Organization, OrgMember.role)
            .join(OrgMember, OrgMember.org_id == Organization.id)
            .where(OrgMember.user_id == user_id)
            .order_by(desc(Organization.created_at))
        )
    ).all()
    org_ids = [organization.id for organization, _role in memberships]
    capabilities_by_org: dict[UUID, list[OrgCapability]] = defaultdict(list)

    if org_ids:
        capabilities = (
            await db.execute(
                select(OrgCapability)
                .where(OrgCapability.org_id.in_(org_ids))
                .order_by(OrgCapability.capability.asc())
            )
        ).scalars()
        for capability in capabilities:
            capabilities_by_org[capability.org_id].append(capability)

    return [
        (organization, role, capabilities_by_org.get(organization.id, []))
        for organization, role in memberships
    ]
