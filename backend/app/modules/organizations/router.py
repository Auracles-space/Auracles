"""FastAPI router for Organizations Core endpoints."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.rate_limit import RateLimiter, RedisCounter
from app.core.redis import get_redis
from app.modules.attestation import matching_service
from app.modules.attestation.models import Attestation, AttestationOffer
from app.modules.attestation.schemas import (
    CredentialEvidenceUploadSessionResponse,
)
from app.modules.auth.models import User
from app.modules.financials import service as financials_service
from app.modules.financials.schemas import (
    EarningsResponse,
    OrgInvoicesResponse,
    OrgPayoutAccountOnboardRequest,
    PayoutAccountOnboardResponse,
    PayoutRequest,
    PayoutResponse,
)
from app.modules.organizations import (
    attestor_application_service,
    nda_service,
    service,
)
from app.modules.organizations.dependencies import OrgContext, require_org_role
from app.modules.organizations.models import OrgAttestorApplication
from app.modules.organizations.schemas import (
    AdminOrgsResponse,
    MyOrganizationResponse,
    MyOrganizationsResponse,
    OrgAcceptOfferRequest,
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
    OrgAttestationItem,
    OrgAttestationOfferItem,
    OrgAttestationOffersResponse,
    OrgAttestationsResponse,
    OrgAttestorAdminListItem,
    OrgAttestorAdminListResponse,
    OrgAttestorApplicationCreateRequest,
    OrgAttestorApplicationResponse,
    OrgAttestorApplicationUpdateRequest,
    OrgAttestorFeedbackRequest,
    OrgAttestorGateChecklist,
    OrgAttestorTaxDocumentRequest,
    OrgInvitationCreateRequest,
    OrgInvitationPreviewResponse,
    OrgInvitationResponse,
    OrgInvitationsResponse,
    OrgMemberResponse,
    OrgMemberRoleUpdateRequest,
    OrgMembersResponse,
    OrgNdaStatusResponse,
    OrgNominateTrialMemberRequest,
    OrgOwnershipTransferRequest,
    OrgReassignReviewerRequest,
    OrgTeamCreateRequest,
    OrgTeamRenameRequest,
    OrgTeamResponse,
    OrgTeamsResponse,
    OrgUndertakingsSignRequest,
    PublicOrganizationResponse,
)

router = APIRouter(prefix="/orgs", tags=["Organizations"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
RedisClient = Annotated[Redis, Depends(get_redis)]
OrgMemberCtx = Annotated[OrgContext, Depends(require_org_role("member"))]
OrgAdmin = Annotated[OrgContext, Depends(require_org_role("admin"))]
OrgOwner = Annotated[OrgContext, Depends(require_org_role("owner"))]

NDA_SIGN_RATE_LIMITER = RateLimiter(namespace="org_nda_sign", limit=5, window=3600)
ORG_ATTESTOR_APPLY_RATE_LIMITER = RateLimiter(
    namespace="org_attestor_apply", limit=3, window=86400
)


def _application_response(
    application: OrgAttestorApplication,
    checklist: OrgAttestorGateChecklist,
) -> OrgAttestorApplicationResponse:
    """Assemble the application response with its derived gate checklist."""
    return OrgAttestorApplicationResponse(
        id=application.id,
        org_id=application.org_id,
        status=application.status,
        legal_name=application.legal_name,
        registration_number=application.registration_number,
        incorporation_doc_keys=application.incorporation_doc_keys,
        sectors=application.sectors,
        framework_categories=application.framework_categories,
        jurisdictions=application.jurisdictions,
        credentials_summary=application.credentials_summary,
        sample_work=application.sample_work,
        professional_references=application.professional_references,
        coi_declarations=application.coi_declarations,
        coi_signed_at=application.coi_signed_at,
        coi_expires_at=application.coi_expires_at,
        confidentiality_signed_at=application.confidentiality_signed_at,
        payout_account_id=application.payout_account_id,
        tax_document_type=application.tax_document_type,
        tax_document_key=application.tax_document_key,
        trial_member_id=application.trial_member_id,
        trial_attestation_id=application.trial_attestation_id,
        kyb_verified_at=application.kyb_verified_at,
        admin_feedback=application.admin_feedback,
        reviewed_at=application.reviewed_at,
        created_at=application.created_at,
        gate_checklist=checklist,
    )


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
        "Organizations the current user belongs to, with role and capability statuses."
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


@router.post(
    "/{org_id}/teams",
    response_model=OrgTeamResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a team",
    description="Create a new team within the organization.",
)
async def create_team(
    org_id: UUID,
    payload: OrgTeamCreateRequest,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgTeamResponse:
    """Create a new team in the organization."""
    del org_id
    return await service.create_team(db=db, context=context, payload=payload)


@router.get(
    "/{org_id}/teams",
    response_model=OrgTeamsResponse,
    summary="List teams",
    description="List all teams in the organization, including member counts.",
)
async def list_teams(
    org_id: UUID,
    context: OrgMemberCtx,
    db: DatabaseSession,
) -> OrgTeamsResponse:
    """List teams in the organization."""
    del org_id
    return await service.list_teams(db=db, context=context)


@router.patch(
    "/{org_id}/teams/{team_id}",
    response_model=OrgTeamResponse,
    summary="Rename a team",
    description="Rename an existing team.",
)
async def rename_team(
    org_id: UUID,
    team_id: UUID,
    payload: OrgTeamRenameRequest,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgTeamResponse:
    """Rename a team in the organization."""
    del org_id
    return await service.rename_team(
        db=db, context=context, team_id=team_id, payload=payload
    )


@router.delete(
    "/{org_id}/teams/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a team",
    description="Delete a team and its membership associations.",
)
async def delete_team(
    org_id: UUID,
    team_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> None:
    """Delete a team in the organization."""
    del org_id
    await service.delete_team(db=db, context=context, team_id=team_id)


@router.put(
    "/{org_id}/teams/{team_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Add a member to a team",
    description="Add an existing organization member to a team (idempotent).",
)
async def add_team_member(
    org_id: UUID,
    team_id: UUID,
    member_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> None:
    """Add a member to a team."""
    del org_id
    await service.add_team_member(
        db=db, context=context, team_id=team_id, member_id=member_id
    )


@router.delete(
    "/{org_id}/teams/{team_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member from a team",
    description="Remove an organization member from a team.",
)
async def remove_team_member(
    org_id: UUID,
    team_id: UUID,
    member_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> None:
    """Remove a member from a team."""
    del org_id
    await service.remove_team_member(
        db=db, context=context, team_id=team_id, member_id=member_id
    )


@router.get(
    "/{org_id}/nda",
    response_model=OrgNdaStatusResponse,
    summary="Get my NDA status",
    description=(
        "Return the caller's platform NDA status for this organization: "
        "whether signing is required (attestor capability pending or "
        "active) and any existing signature."
    ),
)
async def get_nda_status(
    org_id: UUID,
    context: OrgMemberCtx,
    db: DatabaseSession,
) -> OrgNdaStatusResponse:
    """Return the caller's NDA status for one organization."""
    del org_id
    nda_status = await nda_service.get_nda_status(
        db, org_id=context.org.id, user_id=context.user.id
    )
    return OrgNdaStatusResponse(
        required=nda_status.required,
        current_version=nda_status.current_version,
        signed_version=nda_status.signed_version,
        signed_at=nda_status.signed_at,
    )


@router.post(
    "/{org_id}/nda/sign",
    response_model=OrgNdaStatusResponse,
    summary="Sign the platform NDA",
    description=(
        "Sign (or re-sign after a version bump) the platform NDA required "
        "for org attestation work. Rate-limited per user."
    ),
)
async def sign_nda(
    org_id: UUID,
    context: OrgMemberCtx,
    db: DatabaseSession,
    redis: RedisClient,
) -> OrgNdaStatusResponse:
    """Sign the platform NDA as an organization member."""
    del org_id
    await NDA_SIGN_RATE_LIMITER.check(cast(RedisCounter, redis), str(context.user.id))
    await nda_service.sign_nda(db, org_id=context.org.id, user_id=context.user.id)
    nda_status = await nda_service.get_nda_status(
        db, org_id=context.org.id, user_id=context.user.id
    )
    return OrgNdaStatusResponse(
        required=nda_status.required,
        current_version=nda_status.current_version,
        signed_version=nda_status.signed_version,
        signed_at=nda_status.signed_at,
    )


@router.post(
    "/{org_id}/attestor-application",
    response_model=OrgAttestorApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open an org attestor application",
    description=(
        "Open (or reapply for) an attestor-capability application as a draft. "
        "Org owner/admin only."
    ),
)
async def create_attestor_application(
    org_id: UUID,
    payload: OrgAttestorApplicationCreateRequest,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgAttestorApplicationResponse:
    """Create a draft org attestor application."""
    await attestor_application_service.create_application(
        db, org_id=org_id, actor_id=context.user.id, payload=payload
    )
    application, checklist = await attestor_application_service.get_application(
        db, org_id=org_id
    )
    return _application_response(application, checklist)


@router.get(
    "/{org_id}/attestor-application",
    response_model=OrgAttestorApplicationResponse,
    summary="Get the org attestor application",
    description=(
        "Return the org's current attestor application and its gate checklist. "
        "Org owner/admin only."
    ),
)
async def get_attestor_application(
    org_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgAttestorApplicationResponse:
    """Return the org's attestor application with its gate checklist."""
    application, checklist = await attestor_application_service.get_application(
        db, org_id=org_id
    )
    return _application_response(application, checklist)


@router.patch(
    "/{org_id}/attestor-application",
    response_model=OrgAttestorApplicationResponse,
    summary="Edit the org attestor application",
    description=(
        "Partially edit a draft or needs-info application; supply "
        "payout_account_id to link an org-owned payout account. Owner/admin only."
    ),
)
async def update_attestor_application(
    org_id: UUID,
    payload: OrgAttestorApplicationUpdateRequest,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgAttestorApplicationResponse:
    """Partially edit the org's draft attestor application."""
    await attestor_application_service.update_application(
        db, org_id=org_id, actor_id=context.user.id, payload=payload
    )
    application, checklist = await attestor_application_service.get_application(
        db, org_id=org_id
    )
    return _application_response(application, checklist)


@router.post(
    "/{org_id}/attestor-application/submit",
    response_model=OrgAttestorApplicationResponse,
    summary="Submit the org attestor application",
    description=(
        "Submit a completed application for admin review. Rate-limited per org. "
        "Owner/admin only."
    ),
)
async def submit_attestor_application(
    org_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
    redis: RedisClient,
) -> OrgAttestorApplicationResponse:
    """Submit the org's attestor application for review."""
    await ORG_ATTESTOR_APPLY_RATE_LIMITER.check(
        cast(RedisCounter, redis), str(org_id)
    )
    await attestor_application_service.submit_application(
        db, org_id=org_id, actor_id=context.user.id
    )
    application, checklist = await attestor_application_service.get_application(
        db, org_id=org_id
    )
    return _application_response(application, checklist)


@router.post(
    "/{org_id}/attestor-application/sign-undertakings",
    response_model=OrgAttestorApplicationResponse,
    summary="Sign the org attestor undertakings",
    description=(
        "Owner-sign the conflict-of-interest and confidentiality undertakings. "
        "TOTP-gated; org owner only."
    ),
)
async def sign_attestor_undertakings(
    org_id: UUID,
    payload: OrgUndertakingsSignRequest,
    context: OrgOwner,
    db: DatabaseSession,
    redis: RedisClient,
) -> OrgAttestorApplicationResponse:
    """Owner-sign the org attestor undertakings."""
    await attestor_application_service.sign_undertakings(
        db, redis, org_id=org_id, user=context.user, payload=payload
    )
    application, checklist = await attestor_application_service.get_application(
        db, org_id=org_id
    )
    return _application_response(application, checklist)


@router.post(
    "/{org_id}/attestor-application/tax-document",
    response_model=CredentialEvidenceUploadSessionResponse,
    summary="Create a tax-document upload session",
    description=(
        "Create a presigned upload session for the org's tax document and "
        "stamp the document type/key on the application. Owner/admin only."
    ),
)
async def set_attestor_tax_document(
    org_id: UUID,
    payload: OrgAttestorTaxDocumentRequest,
    context: OrgAdmin,
    db: DatabaseSession,
) -> CredentialEvidenceUploadSessionResponse:
    """Create a presigned tax-document upload session for the application."""
    return await attestor_application_service.set_tax_document(
        db, org_id=org_id, actor_id=context.user.id, payload=payload
    )


@router.post(
    "/{org_id}/attestor-application/nominate-trial-member",
    response_model=OrgAttestorApplicationResponse,
    summary="Nominate the trial member",
    description=(
        "Nominate the org member who performs the calibration trial; the member "
        "must have signed the current NDA. Owner/admin only."
    ),
)
async def nominate_attestor_trial_member(
    org_id: UUID,
    payload: OrgNominateTrialMemberRequest,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgAttestorApplicationResponse:
    """Nominate the org member who performs the calibration trial."""
    await attestor_application_service.nominate_trial_member(
        db,
        org_id=org_id,
        actor_id=context.user.id,
        member_id=payload.member_id,
    )
    application, checklist = await attestor_application_service.get_application(
        db, org_id=org_id
    )
    return _application_response(application, checklist)


def _offer_item(
    offer: AttestationOffer,
    attestation: Attestation,
) -> OrgAttestationOfferItem:
    """Build an offer list item from an offer + attestation pair."""
    return OrgAttestationOfferItem(
        offer_id=offer.id,
        attestation_id=attestation.id,
        target_type=attestation.target_type,
        target_id=attestation.target_id,
        status=offer.status,
        cohort_index=offer.cohort_index,
        match_score=float(offer.match_score) if offer.match_score is not None else None,
        offered_at=offer.offered_at,
        expires_at=offer.expires_at,
    )


@router.get(
    "/{org_id}/attestation-offers",
    response_model=OrgAttestationOffersResponse,
    summary="List org attestation offers",
    description="Open and accepted cohort offers made to the org. Owner/admin only.",
)
async def list_org_attestation_offers(
    org_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgAttestationOffersResponse:
    """List cohort offers made to the attestor org."""
    del context
    rows = await matching_service.list_org_offers(db, org_id=org_id)
    return OrgAttestationOffersResponse(
        offers=[_offer_item(offer, attestation) for offer, attestation in rows]
    )


@router.post(
    "/{org_id}/attestation-offers/{offer_id}/accept",
    response_model=OrgAttestationItem,
    summary="Accept and staff an offer",
    description=(
        "Accept a cohort offer and staff it with a reviewing member. "
        "Owner/admin only."
    ),
)
async def accept_org_attestation_offer(
    org_id: UUID,
    offer_id: UUID,
    payload: OrgAcceptOfferRequest,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgAttestationItem:
    """Accept a cohort offer and assign the reviewing member."""
    attestation = await matching_service.accept_org_offer(
        db,
        offer_id=offer_id,
        org_id=org_id,
        actor_id=context.user.id,
        reviewing_member_id=payload.reviewing_member_id,
    )
    return OrgAttestationItem.model_validate(attestation)


@router.post(
    "/{org_id}/attestation-offers/{offer_id}/decline",
    response_model=OrgAttestationItem,
    summary="Decline an offer",
    description="Decline a cohort offer made to the org. Owner/admin only.",
)
async def decline_org_attestation_offer(
    org_id: UUID,
    offer_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgAttestationItem:
    """Decline a cohort offer made to the org."""
    attestation = await matching_service.decline_org_offer(
        db,
        offer_id=offer_id,
        org_id=org_id,
        actor_id=context.user.id,
    )
    return OrgAttestationItem.model_validate(attestation)


@router.post(
    "/{org_id}/attestations/{attestation_id}/reassign",
    response_model=OrgAttestationItem,
    summary="Reassign the reviewing member",
    description=(
        "Reassign the reviewing member of an accepted attestation before its "
        "review starts. Owner/admin only."
    ),
)
async def reassign_org_reviewing_member(
    org_id: UUID,
    attestation_id: UUID,
    payload: OrgReassignReviewerRequest,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgAttestationItem:
    """Reassign the reviewing member before review starts."""
    attestation = await matching_service.reassign_reviewing_member(
        db,
        attestation_id=attestation_id,
        org_id=org_id,
        actor_id=context.user.id,
        reviewing_member_id=payload.reviewing_member_id,
    )
    return OrgAttestationItem.model_validate(attestation)


@router.get(
    "/{org_id}/attestations",
    response_model=OrgAttestationsResponse,
    summary="List org attestations",
    description=(
        "Owner/admin see every org attestation; a plain member sees only the "
        "rows they are staffed on."
    ),
)
async def list_org_attestations(
    org_id: UUID,
    context: OrgMemberCtx,
    db: DatabaseSession,
) -> OrgAttestationsResponse:
    """List the org's attestations, scoped by the caller's role."""
    reviewing_member_id = (
        None if context.member.role in ("owner", "admin") else context.member.id
    )
    rows = await matching_service.list_org_attestations(
        db,
        org_id=org_id,
        reviewing_member_id=reviewing_member_id,
    )
    return OrgAttestationsResponse(
        attestations=[OrgAttestationItem.model_validate(row) for row in rows]
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


@router.get(
    "/{org_id}/financials/earnings",
    response_model=EarningsResponse,
    summary="Organization attestation earnings",
    description=(
        "Released attestation earnings and available payout balance for the "
        "organization. Owner/admin only."
    ),
)
async def get_org_earnings(
    org_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> EarningsResponse:
    """Return the org's released attestation earnings balances."""
    del context
    return await financials_service.get_org_earnings(db, org_id=org_id)


@router.post(
    "/{org_id}/financials/payout-accounts",
    response_model=PayoutAccountOnboardResponse,
    summary="Onboard an organization payout account",
    description=(
        "Create a provider-held payout destination owned by the organization. "
        "Provider routing follows the org's registered country. Owner/admin only."
    ),
)
async def onboard_org_payout_account(
    org_id: UUID,
    payload: OrgPayoutAccountOnboardRequest,
    context: OrgAdmin,
    db: DatabaseSession,
) -> PayoutAccountOnboardResponse:
    """Onboard an org-owned payout destination."""
    del org_id
    return await financials_service.onboard_org_payout_account(
        db, org=context.org, actor=context.user, payload=payload
    )


@router.post(
    "/{org_id}/financials/payouts",
    response_model=PayoutResponse,
    summary="Request an organization payout",
    description=(
        "Request a payout of the org's available attestation earnings. "
        "TOTP-gated (requester's own TOTP); requires an approved attestor "
        "application and a verified org payout account. Owner/admin only."
    ),
)
async def request_org_payout(
    org_id: UUID,
    payload: PayoutRequest,
    context: OrgAdmin,
    db: DatabaseSession,
    redis: RedisClient,
) -> PayoutResponse:
    """Request an org payout after TOTP step-up."""
    return await financials_service.request_org_payout(
        db, redis, org_id=org_id, actor=context.user, payload=payload
    )


@router.get(
    "/{org_id}/financials/invoices",
    response_model=OrgInvoicesResponse,
    summary="Organization issued invoices",
    description=(
        "List invoices issued for the organization's attested work. "
        "Non-sensitive metadata only. Owner/admin only."
    ),
)
async def list_org_invoices(
    org_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgInvoicesResponse:
    """List issued invoices for the org's attested work."""
    del context
    return await financials_service.list_org_invoices(db, org_id=org_id)


admin_orgs_router = APIRouter(
    prefix="/admin/orgs",
    tags=["Admin Organizations"],
)

PlatformAdmin = Annotated[User, Depends(require_role("admin"))]


@admin_orgs_router.get(
    "",
    response_model=AdminOrgsResponse,
    summary="List organizations (platform admin)",
    description=(
        "Paginated organization directory for platform administrators, with "
        "member counts, capability statuses, and slug/name search."
    ),
)
async def admin_list_orgs(
    admin: PlatformAdmin,
    db: DatabaseSession,
    query: str | None = Query(default=None, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AdminOrgsResponse:
    """List/search organizations for platform administration."""
    del admin
    return await service.admin_list_orgs(
        db=db, query=query, page=page, page_size=page_size
    )


@admin_orgs_router.post(
    "/{org_id}/suspend",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Suspend an organization (platform admin)",
    description=(
        "Suspend an organization platform-wide. Idempotent; members lose "
        "org access and derived roles are re-evaluated."
    ),
)
async def admin_suspend_org(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> None:
    """Suspend an organization platform-wide (idempotent)."""
    await service.admin_suspend_org(db=db, admin=admin, org_id=org_id)


@admin_orgs_router.post(
    "/{org_id}/attestor-capability/suspend",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Suspend an org's attestor capability (platform admin)",
    description=(
        "Suspend an org's attestor capability; the profile is retained but "
        "excluded from matching and members' derived roles are re-evaluated."
    ),
)
async def admin_suspend_attestor_capability(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> None:
    """Suspend an org's attestor capability."""
    await attestor_application_service.admin_set_capability_status(
        db, org_id=org_id, admin_id=admin.id, status_value="suspended"
    )


@admin_orgs_router.post(
    "/{org_id}/attestor-capability/reinstate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reinstate an org's attestor capability (platform admin)",
    description=(
        "Reactivate a suspended org attestor capability and its profile; "
        "members' derived roles are re-evaluated."
    ),
)
async def admin_reinstate_attestor_capability(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> None:
    """Reinstate a suspended org attestor capability."""
    await attestor_application_service.admin_set_capability_status(
        db, org_id=org_id, admin_id=admin.id, status_value="active"
    )


@admin_orgs_router.post(
    "/{org_id}/attestor-capability/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an org's attestor capability (platform admin)",
    description=(
        "Revoke an org's attestor capability and deactivate its profile; "
        "members' derived roles are re-evaluated."
    ),
)
async def admin_revoke_attestor_capability(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> None:
    """Revoke an org's attestor capability."""
    await attestor_application_service.admin_set_capability_status(
        db, org_id=org_id, admin_id=admin.id, status_value="revoked"
    )


# Platform-admin org attestor application review pipeline.
admin_org_attestor_router = APIRouter(
    prefix="/admin/org-attestor-applications",
    tags=["Admin Org Attestor"],
)


def _admin_application_response(
    application: OrgAttestorApplication,
    checklist: OrgAttestorGateChecklist,
) -> OrgAttestorApplicationResponse:
    """Assemble the admin application response with its gate checklist."""
    return _application_response(application, checklist)


@admin_org_attestor_router.get(
    "",
    response_model=OrgAttestorAdminListResponse,
    summary="List org attestor applications (platform admin)",
    description="Paginated review queue, optionally filtered by status.",
)
async def admin_list_org_attestor_applications(
    admin: PlatformAdmin,
    db: DatabaseSession,
    status_filter: str | None = Query(default=None, alias="status", max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> OrgAttestorAdminListResponse:
    """List org attestor applications for platform-admin review."""
    del admin
    rows, total = await attestor_application_service.admin_list_applications(
        db, status_filter=status_filter, page=page, page_size=page_size
    )
    return OrgAttestorAdminListResponse(
        applications=[OrgAttestorAdminListItem.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@admin_org_attestor_router.post(
    "/{application_id}/verify-kyb",
    response_model=OrgAttestorApplicationResponse,
    summary="Verify KYB (platform admin)",
    description="Stamp the KYB-verified gate on an application under review.",
)
async def admin_verify_kyb(
    application_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> OrgAttestorApplicationResponse:
    """Verify an application's KYB documents."""
    await attestor_application_service.admin_verify_kyb(
        db, application_id=application_id, admin_id=admin.id
    )
    application, checklist = (
        await attestor_application_service.get_application_by_id(
            db, application_id=application_id
        )
    )
    return _admin_application_response(application, checklist)


@admin_org_attestor_router.post(
    "/{application_id}/needs-info",
    response_model=OrgAttestorApplicationResponse,
    summary="Return an application for more info (platform admin)",
    description="Move a submitted application to needs_info with feedback.",
)
async def admin_needs_info(
    application_id: UUID,
    payload: OrgAttestorFeedbackRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> OrgAttestorApplicationResponse:
    """Return an application to the org for more information."""
    await attestor_application_service.admin_needs_info(
        db,
        application_id=application_id,
        admin_id=admin.id,
        feedback=payload.feedback,
    )
    application, checklist = (
        await attestor_application_service.get_application_by_id(
            db, application_id=application_id
        )
    )
    return _admin_application_response(application, checklist)


@admin_org_attestor_router.post(
    "/{application_id}/start-trial",
    response_model=OrgAttestorApplicationResponse,
    summary="Start the calibration trial (platform admin)",
    description="Assign the calibration trial to the nominated org member.",
)
async def admin_start_trial(
    application_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> OrgAttestorApplicationResponse:
    """Assign the calibration trial to the nominated member."""
    await attestor_application_service.admin_start_trial(
        db, application_id=application_id, admin_id=admin.id
    )
    application, checklist = (
        await attestor_application_service.get_application_by_id(
            db, application_id=application_id
        )
    )
    return _admin_application_response(application, checklist)


@admin_org_attestor_router.post(
    "/{application_id}/approve",
    response_model=OrgAttestorApplicationResponse,
    summary="Approve and activate (platform admin)",
    description=(
        "Approve a fully gated application: create the profile, activate the "
        "attestor capability, and grant every member the derived attestor role."
    ),
)
async def admin_approve(
    application_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> OrgAttestorApplicationResponse:
    """Approve and activate an org attestor application."""
    await attestor_application_service.admin_approve(
        db, application_id=application_id, admin_id=admin.id
    )
    application, checklist = (
        await attestor_application_service.get_application_by_id(
            db, application_id=application_id
        )
    )
    return _admin_application_response(application, checklist)


@admin_org_attestor_router.post(
    "/{application_id}/reject",
    response_model=OrgAttestorApplicationResponse,
    summary="Reject an application (platform admin)",
    description="Terminally reject an application under review with feedback.",
)
async def admin_reject(
    application_id: UUID,
    payload: OrgAttestorFeedbackRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> OrgAttestorApplicationResponse:
    """Terminally reject an org attestor application."""
    await attestor_application_service.admin_reject(
        db,
        application_id=application_id,
        admin_id=admin.id,
        feedback=payload.feedback,
    )
    application, checklist = (
        await attestor_application_service.get_application_by_id(
            db, application_id=application_id
        )
    )
    return _admin_application_response(application, checklist)
