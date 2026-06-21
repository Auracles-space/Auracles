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
from app.modules.projects import dispute_service, milestone_service, service
from app.modules.projects.schemas import (
    AmendmentCreateRequest,
    AmendmentResponse,
    DeliverableResponse,
    DeliverableRevisionRequest,
    DeliverableSubmitRequest,
    DisputeCreateRequest,
    DisputeResponse,
    DisputesResponse,
    FrameworkPrefillResponse,
    MilestoneCreateRequest,
    MilestoneFundingResponse,
    MilestoneResponse,
    MilestonesResponse,
    MilestoneUpdateRequest,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectsResponse,
    ProjectUpdateRequest,
    ProposalCreateRequest,
    ProposalResponse,
    ProposalsResponse,
)
from app.modules.reputation import service as reputation_service
from app.modules.reputation.schemas import ReputationSummary
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
    scope: Literal["open", "assigned"] = Query(default="open"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ProjectsResponse:
    """List Projects for a role.

    Contributors get the open marketplace feed (``scope=open``) or their
    assigned Projects (``scope=assigned``); Operators always get owned Projects.
    """
    return await service.list_projects(
        db=db,
        user=current_user,
        role=role,
        token_roles=token.roles,
        page=page,
        page_size=page_size,
        scope=scope,
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
    response = ProjectResponse.model_validate(project)
    # Surface the Operator's reputation only to a bidding/assigned Contributor —
    # never on the Operator's own view or any public surface (BR-ATT-005).
    if project.operator_id != current_user.id:
        summaries = await reputation_service.summaries_for_subjects(
            db, subject_type="operator", subject_ids=[project.operator_id]
        )
        summary = summaries.get(project.operator_id)
        if summary is not None:
            response.operator_reputation = ReputationSummary.model_validate(summary)
    return response


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


@router.post(
    "/{project_id}/milestones",
    response_model=MilestoneResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_milestone(
    project_id: UUID,
    payload: MilestoneCreateRequest,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> MilestoneResponse:
    """Create a draft Milestone as the accepted Contributor."""
    milestone = await milestone_service.create_milestone(
        db=db,
        contributor=contributor,
        project_id=project_id,
        payload=payload,
    )
    return MilestoneResponse.model_validate(milestone)


@router.get("/{project_id}/milestones", response_model=MilestonesResponse)
async def list_milestones(
    project_id: UUID,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> MilestonesResponse:
    """List Milestones for a Project workspace member."""
    return await milestone_service.list_milestones(
        db=db,
        user=current_user,
        project_id=project_id,
    )


@router.post("/{project_id}/milestones/finalize", response_model=ProjectResponse)
async def finalize_milestone_plan(
    project_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> ProjectResponse:
    """Finalize the Milestone plan once budgets match the accepted Proposal."""
    project = await milestone_service.finalize_milestone_plan(
        db=db,
        contributor=contributor,
        project_id=project_id,
    )
    return ProjectResponse.model_validate(project)


@router.post("/{project_id}/milestones/reopen", response_model=ProjectResponse)
async def reopen_milestone_plan(
    project_id: UUID,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ProjectResponse:
    """Reopen a finalized Milestone plan to draft while no Milestone is funded.

    Open to either Project member so the breakdown can be renegotiated before
    any Escrow is funded.
    """
    project = await milestone_service.reopen_milestone_plan(
        db=db,
        user=current_user,
        project_id=project_id,
    )
    return ProjectResponse.model_validate(project)


@router.post(
    "/{project_id}/milestones/{milestone_id}/fund",
    response_model=MilestoneFundingResponse,
    dependencies=[Depends(require_kyc_verified)],
)
async def fund_milestone(
    project_id: UUID,
    milestone_id: UUID,
    operator: OperatorUser,
    db: DatabaseSession,
) -> MilestoneFundingResponse:
    """Start Stripe escrow funding for a finalized Project Milestone."""
    return await milestone_service.fund_milestone(
        db=db,
        operator=operator,
        project_id=project_id,
        milestone_id=milestone_id,
    )


@router.patch(
    "/{project_id}/milestones/{milestone_id}",
    response_model=MilestoneResponse,
)
async def update_milestone(
    project_id: UUID,
    milestone_id: UUID,
    payload: MilestoneUpdateRequest,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> MilestoneResponse:
    """Update a draft Milestone as the accepted Contributor."""
    milestone = await milestone_service.update_milestone(
        db=db,
        contributor=contributor,
        project_id=project_id,
        milestone_id=milestone_id,
        payload=payload,
    )
    return MilestoneResponse.model_validate(milestone)


@router.post(
    "/{project_id}/milestones/{milestone_id}/deliverables",
    response_model=DeliverableResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_deliverable(
    project_id: UUID,
    milestone_id: UUID,
    payload: DeliverableSubmitRequest,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> DeliverableResponse:
    """Submit work for a funded Milestone as the accepted Contributor."""
    deliverable = await milestone_service.submit_deliverable(
        db=db,
        contributor=contributor,
        project_id=project_id,
        milestone_id=milestone_id,
        payload=payload,
    )
    return DeliverableResponse.model_validate(deliverable)


@router.post(
    "/{project_id}/milestones/{milestone_id}/deliverables/{deliverable_id}/approve",
    response_model=DeliverableResponse,
)
async def approve_deliverable(
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
    operator: OperatorUser,
    db: DatabaseSession,
) -> DeliverableResponse:
    """Approve submitted work and release its Milestone escrow."""
    deliverable = await milestone_service.approve_deliverable(
        db=db,
        operator=operator,
        project_id=project_id,
        milestone_id=milestone_id,
        deliverable_id=deliverable_id,
    )
    return DeliverableResponse.model_validate(deliverable)


@router.post(
    "/{project_id}/milestones/{milestone_id}/deliverables/"
    "{deliverable_id}/request-revision",
    response_model=DeliverableResponse,
)
async def request_deliverable_revision(
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
    payload: DeliverableRevisionRequest,
    operator: OperatorUser,
    db: DatabaseSession,
) -> DeliverableResponse:
    """Send submitted work back for revision as the Project Operator."""
    deliverable = await milestone_service.request_deliverable_revision(
        db=db,
        operator=operator,
        project_id=project_id,
        milestone_id=milestone_id,
        deliverable_id=deliverable_id,
        payload=payload,
    )
    return DeliverableResponse.model_validate(deliverable)


@router.get(
    "/{project_id}/milestones/{milestone_id}/deliverables/"
    "{deliverable_id}/framework-prefill",
    response_model=FrameworkPrefillResponse,
)
async def get_framework_prefill_from_deliverable(
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> FrameworkPrefillResponse:
    """Return draft Framework prefill data for an approved Deliverable."""
    return await milestone_service.build_framework_prefill_from_deliverable(
        db=db,
        contributor=contributor,
        project_id=project_id,
        milestone_id=milestone_id,
        deliverable_id=deliverable_id,
    )


@router.post(
    "/{project_id}/disputes",
    response_model=DisputeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_dispute(
    project_id: UUID,
    payload: DisputeCreateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeResponse:
    """Raise a Milestone dispute as a Project workspace member."""
    dispute = await dispute_service.create_dispute(
        db=db,
        actor=current_user,
        project_id=project_id,
        payload=payload,
    )
    return DisputeResponse.model_validate(dispute)


@router.get("/{project_id}/disputes", response_model=DisputesResponse)
async def list_disputes(
    project_id: UUID,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputesResponse:
    """List disputes visible to a Project workspace member."""
    return await dispute_service.list_project_disputes(
        db=db,
        user=current_user,
        project_id=project_id,
    )


@router.get("/{project_id}/disputes/{dispute_id}", response_model=DisputeResponse)
async def get_dispute(
    project_id: UUID,
    dispute_id: UUID,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeResponse:
    """Return one dispute visible to a Project workspace member."""
    dispute = await dispute_service.get_project_dispute(
        db=db,
        user=current_user,
        project_id=project_id,
        dispute_id=dispute_id,
    )
    return DisputeResponse.model_validate(dispute)


@router.delete(
    "/{project_id}/milestones/{milestone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_milestone(
    project_id: UUID,
    milestone_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> None:
    """Delete a draft Milestone as the accepted Contributor."""
    await milestone_service.delete_milestone(
        db=db,
        contributor=contributor,
        project_id=project_id,
        milestone_id=milestone_id,
    )


@router.post("/{project_id}/close", response_model=ProjectResponse)
async def close_delivered_project(
    project_id: UUID,
    operator: OperatorUser,
    db: DatabaseSession,
) -> ProjectResponse:
    """Close a delivered Project as an archive action."""
    project = await milestone_service.close_delivered_project(
        db=db,
        operator=operator,
        project_id=project_id,
    )
    return ProjectResponse.model_validate(project)


@router.post(
    "/{project_id}/proposals/{proposal_id}/amendments",
    response_model=AmendmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def propose_amendment(
    project_id: UUID,
    proposal_id: UUID,
    payload: AmendmentCreateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AmendmentResponse:
    """Propose scope, budget, or timeline changes for an accepted Proposal."""
    amendment = await service.propose_amendment(
        db=db,
        actor=current_user,
        project_id=project_id,
        proposal_id=proposal_id,
        payload=payload,
    )
    return AmendmentResponse.model_validate(amendment)


@router.post(
    "/{project_id}/proposals/{proposal_id}/amendments/{amendment_id}/accept",
    response_model=AmendmentResponse,
)
async def accept_amendment(
    project_id: UUID,
    proposal_id: UUID,
    amendment_id: UUID,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AmendmentResponse:
    """Accept a pending amendment as the counterparty."""
    amendment = await service.accept_amendment(
        db=db,
        actor=current_user,
        project_id=project_id,
        proposal_id=proposal_id,
        amendment_id=amendment_id,
    )
    return AmendmentResponse.model_validate(amendment)


@router.post(
    "/{project_id}/proposals/{proposal_id}/amendments/{amendment_id}/reject",
    response_model=AmendmentResponse,
)
async def reject_amendment(
    project_id: UUID,
    proposal_id: UUID,
    amendment_id: UUID,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AmendmentResponse:
    """Reject a pending amendment as the counterparty."""
    amendment = await service.reject_amendment(
        db=db,
        actor=current_user,
        project_id=project_id,
        proposal_id=proposal_id,
        amendment_id=amendment_id,
    )
    return AmendmentResponse.model_validate(amendment)


@router.patch(
    "/{project_id}/proposals/{proposal_id}/amendments/{amendment_id}/withdraw",
    response_model=AmendmentResponse,
)
async def withdraw_amendment(
    project_id: UUID,
    proposal_id: UUID,
    amendment_id: UUID,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AmendmentResponse:
    """Withdraw a pending amendment as its proposer."""
    amendment = await service.withdraw_amendment(
        db=db,
        actor=current_user,
        project_id=project_id,
        proposal_id=proposal_id,
        amendment_id=amendment_id,
    )
    return AmendmentResponse.model_validate(amendment)


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


@router.post("/{project_id}/cancel-acceptance", response_model=ProjectResponse)
async def cancel_acceptance(
    project_id: UUID,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ProjectResponse:
    """Cancel an unfunded Proposal acceptance and reopen the Project.

    Open to either Project member while the Project is still ``assigned`` (no
    Escrow funded). Once funding has begun, use the dispute flow instead.
    """
    project = await service.cancel_acceptance(
        db=db,
        user=current_user,
        project_id=project_id,
    )
    return ProjectResponse.model_validate(project)
