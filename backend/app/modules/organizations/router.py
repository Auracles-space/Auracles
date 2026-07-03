"""FastAPI router for Organizations Core endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.redis import get_redis
from app.modules.auth.models import User
from app.modules.organizations import service
from app.modules.organizations.dependencies import OrgContext, require_org_role
from app.modules.organizations.schemas import (
    MyOrganizationResponse,
    MyOrganizationsResponse,
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
    OrgInvitationCreateRequest,
    OrgInvitationPreviewResponse,
    OrgInvitationResponse,
    OrgInvitationsResponse,
    OrgMemberResponse,
    OrgMemberRoleUpdateRequest,
    OrgMembersResponse,
    OrgOwnershipTransferRequest,
    PublicOrganizationResponse,
)

router = APIRouter(prefix="/orgs", tags=["Organizations"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
RedisClient = Annotated[Redis, Depends(get_redis)]
OrgMemberCtx = Annotated[OrgContext, Depends(require_org_role("member"))]
OrgAdmin = Annotated[OrgContext, Depends(require_org_role("admin"))]
OrgOwner = Annotated[OrgContext, Depends(require_org_role("owner"))]


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create organization",
    description="Create a base organization; the creator becomes its owner.",
)
async def create_organization(
    payload: OrganizationCreateRequest,
    user: CurrentUser,
    db: DatabaseSession,
) -> OrganizationResponse:
    """Create an organization for the authenticated user."""
    organization = await service.create_organization(db=db, user=user, payload=payload)
    return OrganizationResponse.model_validate(organization)


@router.get(
    "/mine",
    response_model=MyOrganizationsResponse,
    summary="List my organizations",
    description=(
        "Organizations the current user belongs to, with role and capability "
        "statuses."
    ),
)
async def list_my_organizations(
    user: CurrentUser,
    db: DatabaseSession,
) -> MyOrganizationsResponse:
    """List organizations the authenticated user belongs to."""
    organizations = await service.list_my_organizations(db=db, user_id=user.id)
    return MyOrganizationsResponse(
        organizations=[
            MyOrganizationResponse(
                org=OrganizationResponse.model_validate(organization),
                role=role,
                capabilities={
                    capability.capability: capability.status
                    for capability in capabilities
                },
            )
            for organization, role, capabilities in organizations
        ]
    )


@router.get(
    "/{slug}",
    response_model=PublicOrganizationResponse,
    summary="Public organization profile",
    description=(
        "Return the public organization profile with active capabilities and "
        "member count, excluding member identities and private data."
    ),
)
async def get_public_org(
    slug: str,
    db: DatabaseSession,
) -> PublicOrganizationResponse:
    """Return the public organization profile for the given slug."""
    return await service.get_public_org(db=db, slug=slug)


@router.patch(
    "/{org_id}",
    response_model=OrganizationResponse,
    summary="Update an organization profile",
    description="Update editable organization profile fields as an org admin.",
)
async def update_organization(
    org_id: UUID,
    payload: OrganizationUpdateRequest,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrganizationResponse:
    """Update one organization's editable profile fields."""
    del org_id
    return await service.update_organization(db=db, context=context, payload=payload)


@router.delete(
    "/{org_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate an organization",
    description=(
        "Soft-delete an organization once the owner has wound down all active "
        "capabilities."
    ),
)
async def deactivate_organization(
    org_id: UUID,
    context: OrgOwner,
    db: DatabaseSession,
) -> None:
    """Deactivate one organization as its owner."""
    del org_id
    await service.deactivate_organization(db=db, context=context)


@router.get(
    "/{org_id}/members",
    response_model=OrgMembersResponse,
    summary="List organization members",
    description=(
        "List members of one organization. Member emails are visible only to "
        "org admins and owners."
    ),
)
async def list_members(
    org_id: UUID,
    context: OrgMemberCtx,
    db: DatabaseSession,
) -> OrgMembersResponse:
    """List members of one organization."""
    del org_id
    return await service.list_members(db=db, context=context)


@router.delete(
    "/{org_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an organization member",
    description=(
        "Remove a member from the organization. Non-owner members may remove "
        "themselves to leave the organization."
    ),
)
async def remove_member(
    org_id: UUID,
    member_id: UUID,
    context: OrgMemberCtx,
    db: DatabaseSession,
) -> None:
    """Remove one member or leave the organization."""
    del org_id
    await service.remove_member(db=db, context=context, member_id=member_id)


@router.patch(
    "/{org_id}/members/{member_id}",
    response_model=OrgMemberResponse,
    summary="Change an organization member role",
    description=(
        "Change a member between the member and admin roles. Ownership "
        "changes use the dedicated transfer endpoint."
    ),
)
async def change_member_role(
    org_id: UUID,
    member_id: UUID,
    payload: OrgMemberRoleUpdateRequest,
    context: OrgOwner,
    db: DatabaseSession,
) -> OrgMemberResponse:
    """Change one member between member and admin roles."""
    del org_id
    return await service.change_member_role(
        db=db,
        context=context,
        member_id=member_id,
        new_role=payload.role,
    )


@router.post(
    "/{org_id}/transfer-ownership",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Transfer organization ownership",
    description=(
        "Transfer ownership to another existing member after successful "
        "two-factor verification."
    ),
)
async def transfer_ownership(
    org_id: UUID,
    payload: OrgOwnershipTransferRequest,
    context: OrgOwner,
    db: DatabaseSession,
    redis: RedisClient,
) -> None:
    """Transfer organization ownership to another member."""
    del org_id
    await service.transfer_ownership(
        db=db,
        redis=redis,
        context=context,
        new_owner_member_id=payload.new_owner_member_id,
        totp_code=payload.totp_code,
    )


@router.post(
    "/{org_id}/invitations",
    response_model=OrgInvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite an organization member",
    description=(
        "Create a pending organization invitation, rate-limited per "
        "organization and delivered by email."
    ),
)
async def create_invitation(
    org_id: UUID,
    payload: OrgInvitationCreateRequest,
    context: OrgAdmin,
    db: DatabaseSession,
    redis: RedisClient,
) -> OrgInvitationResponse:
    """Create one pending invitation for an organization."""
    del org_id
    return await service.create_invitation(
        db=db,
        redis=redis,
        context=context,
        payload=payload,
    )


@router.get(
    "/{org_id}/invitations",
    response_model=OrgInvitationsResponse,
    summary="List pending organization invitations",
    description="List pending invitations for one organization.",
)
async def list_invitations(
    org_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgInvitationsResponse:
    """List pending invitations for one organization."""
    del org_id
    return await service.list_invitations(db=db, context=context)


@router.delete(
    "/{org_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an organization invitation",
    description="Revoke one pending invitation for an organization.",
)
async def revoke_invitation(
    org_id: UUID,
    invitation_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> None:
    """Revoke one pending invitation."""
    del org_id
    await service.revoke_invitation(
        db=db,
        context=context,
        invitation_id=invitation_id,
    )


# Invitation response routes — invitee is not yet a member, so no org RBAC.
invitation_router = APIRouter(
    prefix="/org-invitations",
    tags=["Organization Invitations"],
)


@invitation_router.get(
    "/{token}",
    response_model=OrgInvitationPreviewResponse,
    summary="Preview an organization invitation",
    description=(
        "Return the organization name, slug, role, and expiry for a live "
        "invitation. The caller must be authenticated but need not match "
        "the invited email."
    ),
)
async def preview_invitation(
    token: str,
    user: CurrentUser,
    db: DatabaseSession,
) -> OrgInvitationPreviewResponse:
    """Preview an invitation before accepting or declining."""
    del user
    return await service.preview_invitation(db=db, token=token)


@invitation_router.post(
    "/{token}/accept",
    response_model=MyOrganizationResponse,
    summary="Accept an organization invitation",
    description=(
        "Accept a pending invitation. The authenticated user's email must "
        "match the invitation email. Creates a membership row and notifies "
        "the inviter."
    ),
)
async def accept_invitation(
    token: str,
    user: CurrentUser,
    db: DatabaseSession,
) -> MyOrganizationResponse:
    """Accept an invitation and join the organization."""
    return await service.accept_invitation(db=db, user=user, token=token)


@invitation_router.post(
    "/{token}/decline",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Decline an organization invitation",
    description=(
        "Decline a pending invitation without joining. The authenticated "
        "user's email must match the invitation email."
    ),
)
async def decline_invitation(
    token: str,
    user: CurrentUser,
    db: DatabaseSession,
) -> None:
    """Decline an invitation."""
    await service.decline_invitation(db=db, user=user, token=token)

