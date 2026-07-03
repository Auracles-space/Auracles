"""FastAPI router for Organizations Core endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.organizations import service
from app.modules.organizations.dependencies import OrgContext, require_org_role
from app.modules.organizations.schemas import (
    MyOrganizationResponse,
    MyOrganizationsResponse,
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
    PublicOrganizationResponse,
)

router = APIRouter(prefix="/orgs", tags=["Organizations"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
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
