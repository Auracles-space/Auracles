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
from app.modules.organizations.dependencies import (
    OrgContext,
    require_org_capability,
    require_org_role,
)
from app.modules.projects import dispute_service, milestone_service, service
from app.modules.projects.schemas import (
    AmendmentCreateRequest,
    AmendmentResponse,
    DeliverableDownloadResponse,
    DeliverableResponse,
    DeliverableRevisionRequest,
    DeliverablesResponse,
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
    OrgDeliveriesResponse,
    OrgProposalCreateRequest,
    OrgProposalReassignRequest,
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
org_router = APIRouter(prefix="/orgs/{org_id}", tags=["Projects"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
OperatorUser = Annotated[User, Depends(require_role("operator"))]
ContributorUser = Annotated[User, Depends(require_role("contributor"))]
TokenClaims = Annotated[TokenPayload, Depends(get_current_token_payload)]
OrgMemberContext = Annotated[OrgContext, Depends(require_org_role("member"))]
OrgAdminContext = Annotated[OrgContext, Depends(require_org_role("admin"))]


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
    # never on the Operator's own view or any public surface (BR-ATT-005). Only
    # individually-operated Projects carry an operator reputation subject; an
    # org-operated Project has a NULL operator_id and no such subject here.
    if project.operator_id is not None and project.operator_id != current_user.id:
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


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an uncommenced Project",
    description=(
        "Soft-delete an individually-operated open Project that has not commenced."
    ),
)
async def delete_project(
    project_id: UUID,
    operator: OperatorUser,
    db: DatabaseSession,
) -> None:
    """Soft-delete an uncommenced Project owned by the current Operator."""
    await service.delete_project(db=db, operator=operator, project_id=project_id)


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


@org_router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Post organization Project",
    description=(
        "Post a custom Project operated by the organization as an organization "
        "owner or admin while the operator capability is active."
    ),
)
async def create_org_project(
    org_id: UUID,
    payload: ProjectCreateRequest,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("operator"))],
    db: DatabaseSession,
) -> ProjectResponse:
    """Post an organization-operated Project."""
    del org_id
    return await service.create_org_project(
        db=db,
        org_id=context.org.id,
        actor=context.user,
        posting_member_id=context.member.id,
        payload=payload,
    )


@org_router.get(
    "/projects",
    response_model=ProjectsResponse,
    summary="List organization Projects",
    description="List Projects operated by the organization for owners and admins.",
)
async def list_org_projects(
    org_id: UUID,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("operator"))],
    db: DatabaseSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ProjectsResponse:
    """List Projects operated by one organization."""
    del org_id
    return await service.list_org_projects(
        db=db,
        org_id=context.org.id,
        org_name=context.org.name,
        page=page,
        page_size=page_size,
    )


@org_router.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Get an organization Project",
    description=(
        "Return one Project operated by the organization for an owner or admin."
    ),
)
async def get_org_project(
    org_id: UUID,
    project_id: UUID,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("operator"))],
    db: DatabaseSession,
) -> ProjectResponse:
    """Return one organization-operated Project inside its org namespace."""
    del org_id
    return await service.get_org_project(
        db=db,
        org_id=context.org.id,
        project_id=project_id,
        org_name=context.org.name,
    )


@org_router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an uncommenced organization Project",
    description=(
        "Soft-delete an organization-operated open Project that has not commenced."
    ),
)
async def delete_org_project(
    org_id: UUID,
    project_id: UUID,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("operator"))],
    db: DatabaseSession,
) -> None:
    """Soft-delete an uncommenced Project owned by the organization."""
    del org_id
    await service.delete_org_project(
        db=db,
        org_id=context.org.id,
        actor_id=context.user.id,
        project_id=project_id,
    )


@org_router.post(
    "/projects/{project_id}/proposals",
    response_model=ProposalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit organization Proposal",
    description=(
        "Submit a Proposal under the organization contributor identity as an "
        "organization owner or admin while the contributor capability is active."
    ),
)
async def submit_org_proposal(
    org_id: UUID,
    project_id: UUID,
    payload: OrgProposalCreateRequest,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("contributor"))],
    db: DatabaseSession,
) -> ProposalResponse:
    """Submit an organization-owned Proposal for one Project."""
    del org_id
    proposal = await service.submit_org_proposal(
        db=db,
        org_id=context.org.id,
        actor_id=context.user.id,
        project_id=project_id,
        delivering_member_id=payload.delivering_member_id,
        scope=payload.scope,
        budget=payload.budget,
        timeline_days=payload.timeline_days,
        deliverables=[item.model_dump() for item in payload.deliverables],
    )
    return ProposalResponse.model_validate(proposal)


@org_router.get(
    "/projects/{project_id}/proposals",
    response_model=ProposalsResponse,
    summary="List proposals for an organization Project",
    description=(
        "List incoming proposals for a Project operated by the organization."
    ),
)
async def list_org_project_proposals(
    org_id: UUID,
    project_id: UUID,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("operator"))],
    db: DatabaseSession,
) -> ProposalsResponse:
    """Return proposals submitted to one organization-operated Project."""
    del org_id
    return await service.list_org_project_proposals(
        db=db,
        org_id=context.org.id,
        project_id=project_id,
    )


@org_router.post(
    "/proposals/{proposal_id}/reassign",
    response_model=ProposalResponse,
    summary="Reassign organization delivery member",
    description=(
        "Reassign the staffed organization delivery member for accepted work "
        "before funded work has started."
    ),
)
async def reassign_org_proposal(
    org_id: UUID,
    proposal_id: UUID,
    payload: OrgProposalReassignRequest,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("contributor"))],
    db: DatabaseSession,
) -> ProposalResponse:
    """Reassign the staffed member for one organization-owned Proposal."""
    del org_id
    proposal = await service.reassign_delivering_member(
        db=db,
        org_id=context.org.id,
        actor_id=context.user.id,
        proposal_id=proposal_id,
        delivering_member_id=payload.delivering_member_id,
    )
    return ProposalResponse.model_validate(proposal)


@org_router.delete(
    "/proposals/{proposal_id}",
    response_model=ProposalResponse,
    summary="Withdraw organization Proposal",
    description=(
        "Withdraw a pending Proposal submitted under the organization "
        "contributor identity."
    ),
)
async def withdraw_org_proposal(
    org_id: UUID,
    proposal_id: UUID,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("contributor"))],
    db: DatabaseSession,
) -> ProposalResponse:
    """Withdraw one pending organization-owned Proposal."""
    del org_id
    proposal = await service.withdraw_org_proposal(
        db=db,
        org_id=context.org.id,
        actor_id=context.user.id,
        proposal_id=proposal_id,
    )
    return ProposalResponse.model_validate(proposal)


@org_router.get(
    "/proposals",
    response_model=ProposalsResponse,
    summary="List organization Proposals",
    description="List Proposals submitted under the organization identity.",
)
async def list_org_proposals(
    org_id: UUID,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("contributor"))],
    db: DatabaseSession,
) -> ProposalsResponse:
    """List Proposals owned by one organization."""
    del org_id
    return await service.list_org_proposals(
        db=db,
        org_id=context.org.id,
        org_name=context.org.name,
    )


@org_router.get(
    "/deliveries",
    response_model=OrgDeliveriesResponse,
    summary="List organization deliveries",
    description=(
        "List accepted Project workspaces for the organization. Owners and "
        "admins see every accepted workspace; plain members see only work "
        "staffed to themselves."
    ),
)
async def list_org_deliveries(
    org_id: UUID,
    context: OrgMemberContext,
    _: Annotated[None, Depends(require_org_capability("contributor"))],
    db: DatabaseSession,
) -> OrgDeliveriesResponse:
    """List active delivery workspaces for one organization."""
    del org_id
    deliveries = await service.list_org_deliveries(
        db=db,
        org_id=context.org.id,
        member_id=context.member.id,
        member_role=context.member.role,
    )
    return OrgDeliveriesResponse(deliveries=deliveries)


@org_router.post(
    "/projects/{project_id}/proposals/{proposal_id}/accept",
    response_model=ProjectResponse,
    summary="Accept a Proposal for an organization Project",
    description=(
        "Accept a pending Proposal on a Project operated by the organization as "
        "an owner or admin while the operator capability is active."
    ),
)
async def accept_org_proposal(
    org_id: UUID,
    project_id: UUID,
    proposal_id: UUID,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("operator"))],
    db: DatabaseSession,
) -> ProjectResponse:
    """Accept a Proposal on an organization-operated Project."""
    del org_id
    project = await service.accept_org_proposal(
        db=db,
        org_id=context.org.id,
        actor_id=context.user.id,
        project_id=project_id,
        proposal_id=proposal_id,
    )
    return ProjectResponse.model_validate(project)


@org_router.post(
    "/projects/{project_id}/milestones/{milestone_id}/fund",
    response_model=MilestoneFundingResponse,
    summary="Fund an organization Project Milestone",
    description=(
        "Start Stripe escrow funding for a finalized Milestone from the "
        "organization's own Stripe customer as an owner or admin while the "
        "operator capability is active."
    ),
)
async def fund_org_milestone(
    org_id: UUID,
    project_id: UUID,
    milestone_id: UUID,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("operator"))],
    db: DatabaseSession,
) -> MilestoneFundingResponse:
    """Fund an organization-operated Project Milestone from the org customer."""
    del org_id
    return await milestone_service.fund_org_milestone(
        db=db,
        org_id=context.org.id,
        actor_id=context.user.id,
        project_id=project_id,
        milestone_id=milestone_id,
    )


@org_router.post(
    "/projects/{project_id}/deliverables/{deliverable_id}/approve",
    response_model=DeliverableResponse,
    summary="Approve an organization Project Deliverable",
    description=(
        "Approve submitted work on a Project operated by the organization and "
        "release its Milestone escrow to the Contributor as an owner or admin "
        "while the operator capability is active."
    ),
)
async def approve_org_deliverable(
    org_id: UUID,
    project_id: UUID,
    deliverable_id: UUID,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("operator"))],
    db: DatabaseSession,
) -> DeliverableResponse:
    """Approve a Deliverable and release escrow for an organization Project."""
    del org_id
    deliverable = await milestone_service.approve_org_deliverable(
        db=db,
        org_id=context.org.id,
        actor_id=context.user.id,
        project_id=project_id,
        deliverable_id=deliverable_id,
    )
    return DeliverableResponse.model_validate(deliverable)


@org_router.post(
    "/projects/{project_id}/milestones/{milestone_id}/deliverables/"
    "{deliverable_id}/request-revision",
    response_model=DeliverableResponse,
    summary="Request revision on an organization Project Deliverable",
    description=(
        "Return submitted work for revision on a Project operated by the "
        "organization as an owner or admin while the operator capability is active."
    ),
)
async def request_org_deliverable_revision(
    org_id: UUID,
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
    payload: DeliverableRevisionRequest,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("operator"))],
    db: DatabaseSession,
) -> DeliverableResponse:
    """Send submitted work back for revision on an organization Project."""
    del org_id
    deliverable = await milestone_service.request_org_deliverable_revision(
        db=db,
        org_id=context.org.id,
        actor_id=context.user.id,
        project_id=project_id,
        milestone_id=milestone_id,
        deliverable_id=deliverable_id,
        payload=payload,
    )
    return DeliverableResponse.model_validate(deliverable)


@org_router.post(
    "/projects/{project_id}/disputes",
    response_model=DisputeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Raise a dispute on an organization Project",
    description=(
        "Raise a Milestone dispute on a Project operated by the organization as "
        "an owner or admin. Available even when the operator capability is "
        "suspended: disputing protects escrow already committed on an in-flight "
        "milestone, which a suspension must not withhold."
    ),
)
async def create_org_dispute(
    org_id: UUID,
    project_id: UUID,
    payload: DisputeCreateRequest,
    context: OrgAdminContext,
    db: DatabaseSession,
) -> DisputeResponse:
    """Raise a Milestone dispute on an organization-operated Project."""
    del org_id
    dispute = await dispute_service.create_org_dispute(
        db=db,
        org_id=context.org.id,
        actor_id=context.user.id,
        project_id=project_id,
        payload=payload,
    )
    return DisputeResponse.model_validate(dispute)


@org_router.post(
    "/projects/{project_id}/cancel-acceptance",
    response_model=ProjectResponse,
    summary="Cancel an organization Project acceptance",
    description=(
        "Reopen an assigned organization Project before any Milestone is funded."
    ),
)
async def cancel_org_acceptance(
    org_id: UUID,
    project_id: UUID,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("operator"))],
    db: DatabaseSession,
) -> ProjectResponse:
    """Cancel an unfunded acceptance for an organization-operated Project."""
    del org_id
    project = await service.cancel_org_acceptance(
        db=db,
        org_id=context.org.id,
        actor_id=context.user.id,
        project_id=project_id,
    )
    return ProjectResponse.model_validate(project)


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


@router.get(
    "/{project_id}/milestones/{milestone_id}/deliverables",
    response_model=DeliverablesResponse,
)
async def list_deliverables(
    project_id: UUID,
    milestone_id: UUID,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DeliverablesResponse:
    """List a Milestone's Deliverables for either Project member to review."""
    return await milestone_service.list_deliverables(
        db=db,
        user=current_user,
        project_id=project_id,
        milestone_id=milestone_id,
    )


@router.get(
    "/{project_id}/milestones/{milestone_id}/deliverables/{deliverable_id}/download",
    response_model=DeliverableDownloadResponse,
)
async def download_deliverable_files(
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DeliverableDownloadResponse:
    """Return presigned download URLs for a scanned Deliverable's files."""
    return await milestone_service.create_deliverable_download(
        db=db,
        user=current_user,
        project_id=project_id,
        milestone_id=milestone_id,
        deliverable_id=deliverable_id,
    )


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
