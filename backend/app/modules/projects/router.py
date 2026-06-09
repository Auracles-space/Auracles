"""Projects API router."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    get_current_token_payload,
    get_current_user,
    require_kyc_verified,
    require_role,
)
from app.modules.auth.models import User
from app.modules.projects import service
from app.modules.projects.schemas import (
    ProjectCreateRequest,
    ProjectResponse,
    ProjectsResponse,
    ProjectUpdateRequest,
    ProposalCreateRequest,
    ProposalResponse,
    ProposalsResponse,
)
from app.shared.schemas.token import TokenPayload

router = APIRouter(prefix="/projects", tags=["Projects"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
OperatorUser = Annotated[User, Depends(require_role("operator"))]
ContributorUser = Annotated[User, Depends(require_role("contributor"))]
TokenClaims = Annotated[TokenPayload, Depends(get_current_token_payload)]


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_kyc_verified)],
)
async def create_project(
    payload: ProjectCreateRequest,
    operator: OperatorUser,
    db: DatabaseSession,
) -> ProjectResponse:
    """Create an open Project as a KYC-verified Operator."""
    project = await service.create_project(db=db, operator=operator, payload=payload)
    return ProjectResponse.model_validate(project)


@router.get("", response_model=ProjectsResponse)
async def list_projects(
    current_user: CurrentUser,
    token: TokenClaims,
    db: DatabaseSession,
    role: Literal["contributor", "operator"] = Query(...),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ProjectsResponse:
    """List open Projects for Contributors or owned Projects for Operators."""
    return await service.list_projects(
        db=db,
        user=current_user,
        role=role,
        token_roles=token.roles,
        page=page,
        page_size=page_size,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    current_user: CurrentUser,
    token: TokenClaims,
    db: DatabaseSession,
) -> ProjectResponse:
    """Return a Project visible to the current user."""
    project = await service.get_project(
        db=db,
        user=current_user,
        token_roles=token.roles,
        project_id=project_id,
    )
    return ProjectResponse.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdateRequest,
    operator: OperatorUser,
    db: DatabaseSession,
) -> ProjectResponse:
    """Update an Operator-owned Project while it remains open."""
    project = await service.update_project(
        db=db,
        operator=operator,
        project_id=project_id,
        payload=payload,
    )
    return ProjectResponse.model_validate(project)


@router.post(
    "/{project_id}/proposals",
    response_model=ProposalResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_kyc_verified)],
)
async def submit_proposal(
    project_id: UUID,
    payload: ProposalCreateRequest,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> ProposalResponse:
    """Submit a Proposal as a KYC-verified Contributor."""
    proposal = await service.submit_proposal(
        db=db,
        contributor=contributor,
        project_id=project_id,
        payload=payload,
    )
    return ProposalResponse.model_validate(proposal)


@router.get("/{project_id}/proposals", response_model=ProposalsResponse)
async def list_project_proposals(
    project_id: UUID,
    operator: OperatorUser,
    db: DatabaseSession,
) -> ProposalsResponse:
    """List Proposals for an Operator-owned Project."""
    return await service.list_project_proposals(
        db=db,
        operator=operator,
        project_id=project_id,
    )


@router.get("/{project_id}/proposals/mine", response_model=ProposalsResponse)
async def list_my_project_proposals(
    project_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> ProposalsResponse:
    """List the current Contributor's Proposals for a Project."""
    return await service.list_my_project_proposals(
        db=db,
        contributor=contributor,
        project_id=project_id,
    )


@router.patch(
    "/{project_id}/proposals/{proposal_id}/withdraw",
    response_model=ProposalResponse,
)
async def withdraw_proposal(
    project_id: UUID,
    proposal_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> ProposalResponse:
    """Withdraw the current Contributor's pending Proposal."""
    proposal = await service.withdraw_proposal(
        db=db,
        contributor=contributor,
        project_id=project_id,
        proposal_id=proposal_id,
    )
    return ProposalResponse.model_validate(proposal)


@router.post(
    "/{project_id}/proposals/{proposal_id}/accept",
    response_model=ProjectResponse,
)
async def accept_proposal(
    project_id: UUID,
    proposal_id: UUID,
    operator: OperatorUser,
    db: DatabaseSession,
) -> ProjectResponse:
    """Accept one Proposal and assign the Project."""
    project = await service.accept_proposal(
        db=db,
        operator=operator,
        project_id=project_id,
        proposal_id=proposal_id,
    )
    return ProjectResponse.model_validate(project)
