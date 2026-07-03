"""Organizations Core service layer.

Org CRUD, membership, invitations, teams, capability reads, and the
derived attestor-role sync. RBAC lives in dependencies.py, never here.
"""

from __future__ import annotations

import secrets
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.rate_limit import RateLimiter, RedisCounter
from app.core.security import hash_token
from app.modules.auth.models import User
from app.modules.auth.service import verify_totp_for_sensitive_action
from app.modules.notifications.service import create_notification
from app.modules.organizations.dependencies import OrgContext
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgInvitation,
    OrgMember,
    OrgTeam,
    OrgTeamMember,
)
from app.modules.organizations.schemas import (
    MyOrganizationResponse,
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
    OrgInvitationCreateRequest,
    OrgInvitationPreviewResponse,
    OrgInvitationResponse,
    OrgInvitationsResponse,
    OrgMemberResponse,
    OrgMembersResponse,
    OrgTeamCreateRequest,
    OrgTeamRenameRequest,
    OrgTeamResponse,
    OrgTeamsResponse,
    PublicOrganizationResponse,
)
from app.workers.tasks.org_notifications import send_org_invitation

INVITATION_TTL_DAYS = 7
INVITE_RATE_LIMITER = RateLimiter(namespace="org_invite", limit=20, window=3600)


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

    await sync_derived_roles(db, user_id=removed_user_id)


async def sync_derived_roles(db: AsyncSession, *, user_id: UUID) -> None:
    """Grant/revoke the derived user-level attestor role for this user."""
    from app.modules.auth.models import UserRole

    stmt = (
        select(1)
        .select_from(OrgMember)
        .join(Organization, Organization.id == OrgMember.org_id)
        .join(
            OrgCapability,
            (OrgCapability.org_id == Organization.id)
            & (OrgCapability.capability == "can_attest")
            & (OrgCapability.status == "active"),
        )
        .where(
            OrgMember.user_id == user_id,
            Organization.suspended_at.is_(None),
            Organization.deactivated_at.is_(None),
        )
        .limit(1)
    )
    should_have_role = (await db.scalar(stmt)) is not None

    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        current_role = await db.scalar(
            select(UserRole)
            .where(UserRole.user_id == user_id, UserRole.role == "attestor")
            .with_for_update()
        )

        if should_have_role and not current_role:
            new_role = UserRole(user_id=user_id, role="attestor")
            db.add(new_role)
            await write_audit(
                db=db,
                actor_id=user_id,
                action="role_granted",
                target_type="user",
                target_id=user_id,
                metadata={"role": "attestor", "reason": "derived_from_org"},
            )
        elif not should_have_role and current_role:
            await db.delete(current_role)
            await write_audit(
                db=db,
                actor_id=user_id,
                action="role_revoked",
                target_type="user",
                target_id=user_id,
                metadata={"role": "attestor", "reason": "derived_from_org"},
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


async def transfer_ownership(
    db: AsyncSession,
    redis: Redis,
    *,
    context: OrgContext,
    new_owner_member_id: UUID,
    totp_code: str,
) -> None:
    """Transfer organization ownership to another existing member.

    Args:
        db: Async database session.
        redis: Redis client used for TOTP verification state.
        context: Resolved organization/member/user context from RBAC dependency.
        new_owner_member_id: Target membership row that should become owner.
        totp_code: TOTP or backup code provided by the current owner.

    Raises:
        HTTPException(401): The authenticated owner row can no longer be loaded.
        HTTPException(403): The sensitive-action TOTP check fails.
        HTTPException(404): The target membership does not belong to this organization.
        HTTPException(409): The transfer target already owns the organization.
    """
    org_id = context.org.id
    actor_id = context.user.id
    current_member_id = context.member.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        locked_user = await db.get(User, actor_id, with_for_update=True)
        if locked_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
        await verify_totp_for_sensitive_action(
            db=db,
            redis=redis,
            user=locked_user,
            code=totp_code,
        )

        target = await _get_member_row(
            db,
            org_id=org_id,
            member_id=new_owner_member_id,
            for_update=True,
        )
        if target.id == current_member_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already own this organization.",
            )

        current_owner = await db.scalar(
            select(OrgMember)
            .where(
                OrgMember.org_id == org_id,
                OrgMember.role == "owner",
            )
            .with_for_update()
        )
        assert current_owner is not None
        current_owner.role = "admin"
        await db.flush()
        target.role = "owner"
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_ownership_transferred",
            target_type="organization",
            target_id=org_id,
            metadata={"new_owner_user_id": str(target.user_id)},
        )


async def create_invitation(
    db: AsyncSession,
    redis: Redis,
    *,
    context: OrgContext,
    payload: OrgInvitationCreateRequest,
) -> OrgInvitationResponse:
    """Create a pending invitation and dispatch its email after commit.

    Args:
        db: Async database session.
        redis: Redis client used by the per-org invitation rate limiter.
        context: Resolved organization/member/user context from RBAC dependency.
        payload: Lowercased invitee email and requested role.

    Returns:
        The created pending invitation.

    Raises:
        HTTPException(409): The invite already exists or the user is already a member.
        HTTPException(429): This organization exceeded its hourly invite budget.
    """
    org_id = context.org.id
    actor_id = context.user.id
    org_name = context.org.name
    await INVITE_RATE_LIMITER.check(cast(RedisCounter, redis), str(org_id))
    if db.in_transaction():
        await db.rollback()

    raw_token = secrets.token_urlsafe(32)
    email = payload.email
    try:
        async with db.begin():
            existing_member = await db.scalar(
                select(OrgMember)
                .join(User, User.id == OrgMember.user_id)
                .where(
                    OrgMember.org_id == org_id,
                    func.lower(User.email) == email,
                )
            )
            if existing_member is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This user is already a member.",
                )

            invitation = OrgInvitation(
                org_id=org_id,
                email=email,
                role=payload.role,
                invited_by=actor_id,
                status="pending",
                token_hash=hash_token(raw_token),
                expires_at=datetime.now(UTC) + timedelta(days=INVITATION_TTL_DAYS),
            )
            db.add(invitation)
            await db.flush()
            await write_audit(
                db=db,
                actor_id=actor_id,
                action="org_member_invited",
                target_type="organization",
                target_id=org_id,
                metadata={"role": payload.role},
            )
            invitee = await db.scalar(
                select(User).where(func.lower(User.email) == email)
            )
            if invitee is not None:
                await create_notification(
                    db=db,
                    user_id=invitee.id,
                    notification_type="org_invitation_received",
                    title=f"Invitation to join {org_name}",
                    body=f"You've been invited to join {org_name} as {payload.role}.",
                    link="/settings/organizations",
                    payload={"org_id": str(org_id)},
                    dedupe_key=f"org-invitation-received:{invitation.id}",
                )
            response = OrgInvitationResponse.model_validate(invitation)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending invitation for this email already exists.",
        ) from exc

    send_org_invitation.delay(email, org_name, payload.role, raw_token)
    return response


async def list_invitations(
    db: AsyncSession,
    *,
    context: OrgContext,
) -> OrgInvitationsResponse:
    """List pending invitations for one organization.

    Args:
        db: Async database session.
        context: Resolved organization/member/user context from RBAC dependency.

    Returns:
        Pending invitations ordered newest-first.
    """
    invitations = (
        await db.scalars(
            select(OrgInvitation)
            .where(
                OrgInvitation.org_id == context.org.id,
                OrgInvitation.status == "pending",
            )
            .order_by(OrgInvitation.created_at.desc(), OrgInvitation.id.desc())
        )
    ).all()
    return OrgInvitationsResponse(
        invitations=[
            OrgInvitationResponse.model_validate(invitation)
            for invitation in invitations
        ]
    )


async def revoke_invitation(
    db: AsyncSession,
    *,
    context: OrgContext,
    invitation_id: UUID,
) -> None:
    """Revoke one pending organization invitation.

    Args:
        db: Async database session.
        context: Resolved organization/member/user context from RBAC dependency.
        invitation_id: Invitation id scoped to this organization.

    Raises:
        HTTPException(404): Invitation does not belong to this organization.
        HTTPException(409): Only pending invitations can be revoked.
    """
    org_id = context.org.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        invitation = await db.scalar(
            select(OrgInvitation)
            .where(
                OrgInvitation.id == invitation_id,
                OrgInvitation.org_id == org_id,
            )
            .with_for_update()
        )
        if invitation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation not found.",
            )
        if invitation.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only pending invitations can be revoked.",
            )
        invitation.status = "revoked"
        invitation.responded_at = datetime.now(UTC)


async def _get_live_invitation(
    db: AsyncSession,
    *,
    token: str,
) -> tuple[OrgInvitation, Organization]:
    """Resolve a pending invitation and its active org by raw token.

    Args:
        db: Async database session.
        token: Raw invitation token from the URL path.

    Returns:
        The pending invitation and its active organization.

    Raises:
        HTTPException(404): Unknown token, terminal status, or dead org.
        HTTPException(409): Token has a terminal status (accepted/declined/revoked).
        HTTPException(410): Pending but past its expiry timestamp.
    """
    invitation = await db.scalar(
        select(OrgInvitation).where(
            OrgInvitation.token_hash == hash_token(token)
        )
    )
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found.",
        )
    if invitation.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invitation is not available.",
        )
    organization = await db.scalar(
        select(Organization).where(
            Organization.id == invitation.org_id,
            Organization.deactivated_at.is_(None),
            Organization.suspended_at.is_(None),
        )
    )
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation is not available.",
        )
    if invitation.expires_at < datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Invitation has expired.",
        )
    return invitation, organization


async def preview_invitation(
    db: AsyncSession,
    *,
    token: str,
) -> OrgInvitationPreviewResponse:
    """Return a preview of a live invitation without consuming it.

    Args:
        db: Async database session.
        token: Raw invitation token from the URL path.

    Returns:
        The org name, slug, invited role, and expiry for the invitee to review.

    Raises:
        HTTPException(404/409/410): Delegated from _get_live_invitation.
    """
    invitation, organization = await _get_live_invitation(db, token=token)
    return OrgInvitationPreviewResponse(
        org_name=organization.name,
        org_slug=organization.slug,
        role=invitation.role,
        expires_at=invitation.expires_at,
    )


async def accept_invitation(
    db: AsyncSession,
    *,
    user: User,
    token: str,
) -> MyOrganizationResponse:
    """Accept an invitation and join the organization.

    Args:
        db: Async database session.
        user: Authenticated user accepting the invitation.
        token: Raw invitation token from the URL path.

    Returns:
        The new membership in the MyOrganizationResponse shape.

    Raises:
        HTTPException(403): Authenticated user's email does not match the invite.
        HTTPException(404/409/410): Delegated from _get_live_invitation.
    """
    invitation, organization = await _get_live_invitation(db, token=token)
    if user.email.lower() != invitation.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invitation was sent to a different email address.",
        )

    # Extract all primitive values before rollback/begin expires them
    invitation_id = invitation.id
    invited_role = invitation.role
    invited_by = invitation.invited_by
    org_id = organization.id
    org_name = organization.name
    user_id = user.id
    user_display_name = user.display_name

    if db.in_transaction():
        await db.rollback()

    try:
        async with db.begin():
            # Re-load under lock to prevent double-accept races
            locked_invitation = await db.scalar(
                select(OrgInvitation)
                .where(OrgInvitation.id == invitation_id)
                .with_for_update()
            )
            if locked_invitation is None or locked_invitation.status != "pending":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Invitation is not available.",
                )
            locked_invitation.status = "accepted"
            locked_invitation.responded_at = datetime.now(UTC)

            member = OrgMember(
                org_id=org_id,
                user_id=user_id,
                role=invited_role,
            )
            db.add(member)
            await write_audit(
                db=db,
                actor_id=user_id,
                action="org_member_joined",
                target_type="organization",
                target_id=org_id,
                metadata={"role": invited_role},
            )
            await create_notification(
                db=db,
                user_id=invited_by,
                notification_type="org_invitation_accepted",
                title=f"{user_display_name} joined {org_name}",
                body=f"{user_display_name} accepted the invitation to join {org_name}.",
                link="/settings/organizations",
                payload={"org_id": str(org_id)},
                dedupe_key=f"org-invite-accepted:{invitation_id}",
            )
    except IntegrityError as exc:
        # Invitee is already a member (e.g. email changed after joining
        # another way) — surface the unique-membership violation as 409.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already a member of this organization.",
        ) from exc

    await sync_derived_roles(db, user_id=user_id)

    # Build the MyOrganizationResponse shape
    capabilities: dict[str, str] = {}
    cap_rows = (
        await db.scalars(
            select(OrgCapability).where(
                OrgCapability.org_id == org_id
            )
        )
    ).all()
    for cap in cap_rows:
        capabilities[cap.capability] = cap.status

    # Reload the organization from the DB after the transaction is complete
    org_obj = await db.scalar(
        select(Organization).where(Organization.id == org_id)
    )
    if org_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )

    return MyOrganizationResponse(
        org=OrganizationResponse.model_validate(org_obj),
        role=invited_role,
        capabilities=capabilities,
    )


async def decline_invitation(
    db: AsyncSession,
    *,
    user: User,
    token: str,
) -> None:
    """Decline an invitation without joining.

    Args:
        db: Async database session.
        user: Authenticated user declining the invitation.
        token: Raw invitation token from the URL path.

    Raises:
        HTTPException(403): Authenticated user's email does not match the invite.
        HTTPException(404/409/410): Delegated from _get_live_invitation.
    """
    invitation, organization = await _get_live_invitation(db, token=token)
    if user.email.lower() != invitation.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invitation was sent to a different email address.",
        )

    # Extract all primitive values before rollback/begin expires them
    invitation_id = invitation.id
    invited_by = invitation.invited_by
    org_id = organization.id
    org_name = organization.name
    user_display_name = user.display_name

    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        locked_invitation = await db.scalar(
            select(OrgInvitation)
            .where(OrgInvitation.id == invitation_id)
            .with_for_update()
        )
        if locked_invitation is None or locked_invitation.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Invitation is not available.",
            )
        locked_invitation.status = "declined"
        locked_invitation.responded_at = datetime.now(UTC)

        await create_notification(
            db=db,
            user_id=invited_by,
            notification_type="org_invitation_declined",
            title=f"{user_display_name} declined the invitation",
            body=f"{user_display_name} declined the invitation to join {org_name}.",
            link="/settings/organizations",
            payload={"org_id": str(org_id)},
            dedupe_key=f"org-invite-declined:{invitation_id}",
        )


async def create_team(
    db: AsyncSession,
    *,
    context: OrgContext,
    payload: OrgTeamCreateRequest,
) -> OrgTeamResponse:
    """Create a new team in the organization."""
    org_id = context.org.id
    user_id = context.user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        team = OrgTeam(org_id=org_id, name=payload.name)
        db.add(team)
        try:
            await db.flush()
        except IntegrityError as exc:
            if "uq_org_teams_org_name" in str(exc):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A team with this name already exists.",
                ) from exc
            raise
        await write_audit(
            db=db,
            actor_id=user_id,
            action="org_team_created",
            target_type="org",
            target_id=org_id,
            metadata={"team_id": str(team.id), "team_name": team.name},
        )
        return OrgTeamResponse(
            id=team.id,
            name=team.name,
            member_count=0,
            created_at=team.created_at,
        )


async def list_teams(
    db: AsyncSession,
    *,
    context: OrgContext,
) -> OrgTeamsResponse:
    """List teams in the organization."""
    org_id = context.org.id
    stmt = (
        select(
            OrgTeam.id,
            OrgTeam.name,
            OrgTeam.created_at,
            func.count(OrgTeamMember.member_id).label("member_count"),
        )
        .outerjoin(OrgTeamMember, OrgTeamMember.team_id == OrgTeam.id)
        .where(OrgTeam.org_id == org_id)
        .group_by(OrgTeam.id)
        .order_by(OrgTeam.name)
    )
    rows = (await db.execute(stmt)).all()
    return OrgTeamsResponse(
        teams=[
            OrgTeamResponse(
                id=row.id,
                name=row.name,
                member_count=row.member_count,  # type: ignore[arg-type]
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


async def rename_team(
    db: AsyncSession,
    *,
    context: OrgContext,
    team_id: UUID,
    payload: OrgTeamRenameRequest,
) -> OrgTeamResponse:
    """Rename a team in the organization."""
    org_id = context.org.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        team = await db.scalar(
            select(OrgTeam).where(
                OrgTeam.id == team_id, OrgTeam.org_id == org_id
            ).with_for_update()
        )
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")

        team.name = payload.name
        try:
            await db.flush()
        except IntegrityError as exc:
            if "uq_org_teams_org_name" in str(exc):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A team with this name already exists.",
                ) from exc
            raise

        member_count = await db.scalar(
            select(func.count(OrgTeamMember.member_id)).where(OrgTeamMember.team_id == team_id)
        )

        return OrgTeamResponse(
            id=team.id,
            name=team.name,
            member_count=member_count or 0,
            created_at=team.created_at,
        )


async def delete_team(
    db: AsyncSession,
    *,
    context: OrgContext,
    team_id: UUID,
) -> None:
    """Delete a team in the organization."""
    org_id = context.org.id
    user_id = context.user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        team = await db.scalar(
            select(OrgTeam).where(
                OrgTeam.id == team_id, OrgTeam.org_id == org_id
            )
        )
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")

        team_name = team.name
        await db.delete(team)

        await write_audit(
            db=db,
            actor_id=user_id,
            action="org_team_deleted",
            target_type="org",
            target_id=org_id,
            metadata={"team_id": str(team_id), "team_name": team_name},
        )


async def add_team_member(
    db: AsyncSession,
    *,
    context: OrgContext,
    team_id: UUID,
    member_id: UUID,
) -> None:
    """Add a member to a team."""
    org_id = context.org.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        team = await db.scalar(
            select(OrgTeam).where(OrgTeam.id == team_id, OrgTeam.org_id == org_id)
        )
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")

        await _get_member_row(db, org_id=org_id, member_id=member_id)

        stmt = pg_insert(OrgTeamMember).values(
            team_id=team_id, member_id=member_id
        ).on_conflict_do_nothing()
        await db.execute(stmt)


async def remove_team_member(
    db: AsyncSession,
    *,
    context: OrgContext,
    team_id: UUID,
    member_id: UUID,
) -> None:
    """Remove a member from a team."""
    org_id = context.org.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        team = await db.scalar(
            select(OrgTeam).where(OrgTeam.id == team_id, OrgTeam.org_id == org_id)
        )
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")

        member_row = await db.scalar(
            select(OrgTeamMember).where(
                OrgTeamMember.team_id == team_id,
                OrgTeamMember.member_id == member_id
            )
        )
        if not member_row:
            raise HTTPException(status_code=404, detail="Member is not in this team.")

        await db.delete(member_row)
