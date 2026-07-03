"""Organizations Core service layer.

Org CRUD, membership, invitations, teams, capability reads, and the
derived attestor-role sync. RBAC lives in dependencies.py, never here.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.auth.models import User
from app.modules.organizations.dependencies import OrgContext
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgMember,
)
from app.modules.organizations.schemas import (
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
    OrgMemberResponse,
    OrgMembersResponse,
    PublicOrganizationResponse,
)


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
            .where(
                OrgMember.user_id == user_id,
                Organization.deactivated_at.is_(None),
            )
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


async def get_public_org(
    db: AsyncSession,
    *,
    slug: str,
) -> PublicOrganizationResponse:
    """Return the public profile for an active organization by slug.

    Args:
        db: Async database session.
        slug: Public organization slug from the request path.

    Returns:
        The public-safe organization profile.

    Raises:
        HTTPException(404): If the organization is unknown, deactivated, or suspended.
    """
    organization = await db.scalar(
        select(Organization).where(
            func.lower(Organization.slug) == slug.lower(),
            Organization.deactivated_at.is_(None),
            Organization.suspended_at.is_(None),
        )
    )
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )

    member_count = (
        await db.scalar(
            select(func.count())
            .select_from(OrgMember)
            .where(OrgMember.org_id == organization.id)
        )
    ) or 0
    active_capabilities = list(
        (
            await db.scalars(
                select(OrgCapability.capability).where(
                    OrgCapability.org_id == organization.id,
                    OrgCapability.status == "active",
                )
            )
        ).all()
    )

    return PublicOrganizationResponse(
        slug=organization.slug,
        name=organization.name,
        logo_key=organization.logo_key,
        country=organization.country,
        website=organization.website,
        description=organization.description,
        active_capabilities=sorted(active_capabilities),
        member_count=member_count,
        created_at=organization.created_at,
    )


async def update_organization(
    db: AsyncSession,
    *,
    context: OrgContext,
    payload: OrganizationUpdateRequest,
) -> OrganizationResponse:
    """Apply a partial organization profile update.

    Args:
        db: Async database session.
        context: Resolved organization/member/user context from RBAC dependency.
        payload: Partial update fields for the organization.

    Returns:
        The updated organization response.
    """
    org_id = context.org.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        organization = await db.scalar(
            select(Organization).where(Organization.id == org_id)
        )
        assert organization is not None
        for field in ("name", "website", "description", "logo_key"):
            value = getattr(payload, field)
            if value is not None:
                setattr(organization, field, value)

    await db.refresh(organization)
    return OrganizationResponse.model_validate(organization)


async def deactivate_organization(
    db: AsyncSession,
    *,
    context: OrgContext,
) -> None:
    """Soft-delete an organization once all active capabilities are wound down.

    Args:
        db: Async database session.
        context: Resolved organization/member/user context from RBAC dependency.

    Raises:
        HTTPException(409): If any capability remains active.
    """
    org_id = context.org.id
    actor_id = context.user.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        active_capabilities = await db.scalar(
            select(func.count())
            .select_from(OrgCapability)
            .where(
                OrgCapability.org_id == org_id,
                OrgCapability.status == "active",
            )
        )
        if active_capabilities:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Wind down active capabilities before deactivating the "
                    "organization."
                ),
            )

        organization = await db.scalar(
            select(Organization)
            .where(Organization.id == org_id)
            .with_for_update()
        )
        assert organization is not None
        organization.deactivated_at = datetime.now(UTC)
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_deactivated",
            target_type="organization",
            target_id=organization.id,
        )


async def list_members(
    db: AsyncSession,
    *,
    context: OrgContext,
) -> OrgMembersResponse:
    """List organization members with caller-scoped email visibility.

    Args:
        db: Async database session.
        context: Resolved organization/member/user context from RBAC dependency.

    Returns:
        The organization's members ordered by join time.
    """
    include_email = context.member.role in {"owner", "admin"}
    rows = (
        await db.execute(
            select(OrgMember, User.display_name, User.email)
            .join(User, User.id == OrgMember.user_id)
            .where(OrgMember.org_id == context.org.id)
            .order_by(OrgMember.joined_at.asc(), OrgMember.id.asc())
        )
    ).all()
    return OrgMembersResponse(
        members=[
            OrgMemberResponse(
                id=member.id,
                user_id=member.user_id,
                display_name=display_name,
                email=email if include_email else None,
                role=member.role,
                joined_at=member.joined_at,
            )
            for member, display_name, email in rows
        ]
    )


async def _get_member_row(
    db: AsyncSession,
    *,
    org_id: UUID,
    member_id: UUID,
    for_update: bool = False,
) -> OrgMember:
    """Load one member row for an organization or raise 404."""
    statement = select(OrgMember).where(
        OrgMember.id == member_id,
        OrgMember.org_id == org_id,
    )
    if for_update:
        statement = statement.with_for_update()
    member = await db.scalar(statement)
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found.",
        )
    return member


async def remove_member(
    db: AsyncSession,
    *,
    context: OrgContext,
    member_id: UUID,
) -> None:
    """Remove a member or allow a non-owner to leave the organization.

    Args:
        db: Async database session.
        context: Resolved organization/member/user context from RBAC dependency.
        member_id: Target membership row id in this organization.

    Raises:
        HTTPException(403): Caller lacks permission to remove the target member.
        HTTPException(404): Target member does not belong to this organization.
        HTTPException(409): The organization owner cannot be removed.
    """
    org_id = context.org.id
    actor_id = context.user.id
    caller_role = context.member.role
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        target = await _get_member_row(
            db,
            org_id=org_id,
            member_id=member_id,
            for_update=True,
        )
        if target.role == "owner":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Transfer ownership before removing the owner.",
            )

        is_self = target.user_id == actor_id
        if not is_self and caller_role == "member":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to remove this member.",
            )
        if caller_role == "admin" and target.role == "admin" and not is_self:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner can remove an admin.",
            )

        removed_user_id = target.user_id
        await db.delete(target)
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_member_removed",
            target_type="organization",
            target_id=org_id,
            metadata={
                "removed_user_id": str(removed_user_id),
                "self_removed": is_self,
            },
        )


async def change_member_role(
    db: AsyncSession,
    *,
    context: OrgContext,
    member_id: UUID,
    new_role: str,
) -> OrgMemberResponse:
    """Change one member between the member and admin roles.

    Args:
        db: Async database session.
        context: Resolved organization/member/user context from RBAC dependency.
        member_id: Target membership row id in this organization.
        new_role: The replacement role, restricted to ``member`` or ``admin``.

    Returns:
        The updated member response with email included for the owner caller.

    Raises:
        HTTPException(404): Target member does not belong to this organization.
        HTTPException(409): The owner role must be moved through transfer flow.
    """
    org_id = context.org.id
    actor_id = context.user.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        target = await _get_member_row(
            db,
            org_id=org_id,
            member_id=member_id,
            for_update=True,
        )
        if target.role == "owner":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Use transfer ownership to change the owner role.",
            )

        old_role = target.role
        target.role = new_role
        user_row = await db.scalar(select(User).where(User.id == target.user_id))
        assert user_row is not None
        if old_role != new_role:
            await write_audit(
                db=db,
                actor_id=actor_id,
                action="org_member_role_changed",
                target_type="organization",
                target_id=org_id,
                metadata={
                    "member_user_id": str(target.user_id),
                    "from_role": old_role,
                    "to_role": new_role,
                },
            )
        return OrgMemberResponse(
            id=target.id,
            user_id=target.user_id,
            display_name=user_row.display_name,
            email=user_row.email,
            role=target.role,
            joined_at=target.joined_at,
        )
