"""FastAPI router for Organizations Core endpoints."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
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
    PurchaseRequest,
    PurchaseResponse,
)
from app.modules.frameworks import service as frameworks_service
from app.modules.frameworks.schemas import (
    FrameworkReviewCreate,
    FrameworkReviewResponse,
)
from app.modules.library.schemas import ArtifactDownloadResponse
from app.modules.organizations import (
    attestor_application_service,
    billing_service,
    contributor_directory_service,
    contributor_service,
    legal_profile_service,
    library_service,
    nda_service,
    operator_service,
    service,
)
from app.modules.organizations.dependencies import (
    OrgContext,
    require_org_capability,
    require_org_role,
)
from app.modules.organizations.models import OrgAttestorApplication, OrgLegalProfile
from app.modules.organizations.schemas import (
    AdminOrgsResponse,
    ContributorOrgDirectoryEntry,
    ContributorOrgDirectoryResponse,
    LogoConfirmRequest,
    LogoUploadUrlRequest,
    LogoUploadUrlResponse,
    MyInvitationsResponse,
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
    OrgCapabilityResponse,
    OrgInvitationCreateRequest,
    OrgInvitationPreviewResponse,
    OrgInvitationResponse,
    OrgInvitationsResponse,
    OrgLegalProfileResponse,
    OrgLegalProfileUpdateRequest,
    OrgLibraryItem,
    OrgLibraryResponse,
    OrgLicenseGrantRequest,
    OrgLicenseGrantResponse,
    OrgLicenseGrantsResponse,
    OrgMemberResponse,
    OrgMemberRoleUpdateRequest,
    OrgMembersResponse,
    OrgNdaStatusResponse,
    OrgNominateTrialMemberRequest,
    OrgOwnershipTransferRequest,
    OrgPaymentMethodDeleteRequest,
    OrgPaymentMethodDeleteResponse,
    OrgPaymentMethodResponse,
    OrgPaymentMethodSetupRequest,
    OrgPaymentMethodSetupResponse,
    OrgPaymentMethodsResponse,
    OrgReassignReviewerRequest,
    OrgTeamCreateRequest,
    OrgTeamRenameRequest,
    OrgTeamResponse,
    OrgTeamsResponse,
    OrgUndertakingsSignRequest,
    PublicOrganizationResponse,
)

router = APIRouter(prefix="/orgs", tags=["Organizations"])
public_router = APIRouter(prefix="/contributors", tags=["Organizations"])
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
ORG_CONTRIBUTOR_ACTIVATE_RATE_LIMITER = RateLimiter(
    namespace="org_contributor_activate", limit=5, window=3600
)
ORG_OPERATOR_ACTIVATE_RATE_LIMITER = RateLimiter(
    namespace="org_operator_activate", limit=5, window=3600
)
ORG_PAYMENT_METHOD_SETUP_RATE_LIMITER = RateLimiter(
    namespace="org_payment_method_setup", limit=10, window=3600
)
ORG_FRAMEWORK_PURCHASE_RATE_LIMITER = RateLimiter(
    namespace="org_framework_purchase", limit=30, window=3600
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


def _legal_profile_response(profile: OrgLegalProfile) -> OrgLegalProfileResponse:
    """Map one org legal-profile row to an owner-visible response schema."""
    return OrgLegalProfileResponse(
        org_id=profile.org_id,
        legal_name=profile.legal_name,
        registration_number=profile.registration_number,
        address=cast("dict[str, object] | None", profile.address),
        tax_document_type=profile.tax_document_type,
        tax_document_uploaded=profile.tax_document_key is not None,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
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


@public_router.get(
    "",
    response_model=ContributorOrgDirectoryResponse,
    summary="List public contributor organizations",
    description=(
        "Return active contributor organizations for public directory browsing, "
        "including only org identity, verification, reputation, and aggregate counts."
    ),
)
async def list_public_contributor_orgs(
    db: DatabaseSession,
) -> ContributorOrgDirectoryResponse:
    """Return active public contributor-organization directory entries."""
    return ContributorOrgDirectoryResponse(
        contributors=await contributor_directory_service.list_contributor_orgs(db)
    )


@public_router.get(
    "/{org_slug}",
    response_model=ContributorOrgDirectoryEntry,
    summary="Get public contributor organization profile",
    description=(
        "Return one active contributor organization's public profile without "
        "member identities or internal staffing metadata."
    ),
)
async def get_public_contributor_org(
    org_slug: str,
    db: DatabaseSession,
) -> ContributorOrgDirectoryEntry:
    """Return one active public contributor-organization directory entry."""
    return await contributor_directory_service.get_contributor_org(
        db,
        org_slug=org_slug,
    )


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


@router.post(
    "/{org_id}/logo/upload-url",
    response_model=LogoUploadUrlResponse,
    summary="Request an organization logo upload URL",
    description=(
        "Return a presigned POST target for the organization logo. Image type "
        "and size are validated before the target is issued. Org admin only."
    ),
)
async def request_org_logo_upload_url(
    org_id: UUID,
    payload: LogoUploadUrlRequest,
    context: OrgAdmin,
) -> LogoUploadUrlResponse:
    """Return a presigned logo upload target for an org admin."""
    del org_id
    return service.request_org_logo_upload_url(context=context, payload=payload)


@router.post(
    "/{org_id}/logo/confirm",
    response_model=OrganizationResponse,
    summary="Confirm an organization logo upload",
    description=(
        "Confirm a completed logo upload and publish it on the organization. "
        "The object must exist and the key must belong to the org. Admin only."
    ),
)
async def confirm_org_logo_upload(
    org_id: UUID,
    payload: LogoConfirmRequest,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrganizationResponse:
    """Persist an organization logo after verifying the upload."""
    del org_id
    return await service.confirm_org_logo_upload(db, context=context, payload=payload)


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


@router.post(
    "/{org_id}/contributor-capability/activate",
    response_model=OrgCapabilityResponse,
    summary="Activate contributor capability",
    description=(
        "Self-activate the organization's contributor capability as an org "
        "admin or owner. Creates the org contributor profile if missing and "
        "grants members the derived contributor role."
    ),
)
async def activate_contributor_capability(
    org_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
    redis: RedisClient,
) -> OrgCapabilityResponse:
    """Activate the org Contributor capability."""
    del org_id
    await ORG_CONTRIBUTOR_ACTIVATE_RATE_LIMITER.check(
        cast(RedisCounter, redis), str(context.org.id)
    )
    capability = await contributor_service.activate_contributor_capability(
        db,
        org_id=context.org.id,
        actor_id=context.user.id,
    )
    return OrgCapabilityResponse.model_validate(capability)


@router.post(
    "/{org_id}/operator-capability/activate",
    response_model=OrgCapabilityResponse,
    summary="Activate operator capability",
    description=(
        "Self-activate the organization's operator capability as an org "
        "admin or owner and grant members the derived operator role."
    ),
)
async def activate_operator_capability(
    org_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
    redis: RedisClient,
) -> OrgCapabilityResponse:
    """Activate the org Operator capability."""
    del org_id
    await ORG_OPERATOR_ACTIVATE_RATE_LIMITER.check(
        cast(RedisCounter, redis), str(context.org.id)
    )
    capability = await operator_service.activate_operator_capability(
        db,
        org_id=context.org.id,
        actor_id=context.user.id,
    )
    return OrgCapabilityResponse.model_validate(capability)


@router.post(
    "/{org_id}/licenses/{license_id}/grants",
    response_model=OrgLicenseGrantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add an organization license grant",
    description=(
        "Allocate one org-owned License to exactly one team or one member."
    ),
)
async def add_org_license_grant(
    org_id: UUID,
    license_id: UUID,
    payload: OrgLicenseGrantRequest,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgLicenseGrantResponse:
    """Create one org License grant for a team or member."""
    del org_id
    grant = await library_service.add_license_grant(
        db,
        org_id=context.org.id,
        license_id=license_id,
        actor_member_id=context.member.id,
        team_id=payload.team_id,
        member_id=payload.member_id,
    )
    return OrgLicenseGrantResponse.model_validate(grant)


@router.delete(
    "/{org_id}/licenses/{license_id}/grants/{grant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an organization license grant",
    description="Remove one team or member allocation from an org-owned License.",
)
async def revoke_org_license_grant(
    org_id: UUID,
    license_id: UUID,
    grant_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> None:
    """Delete one org License grant."""
    del org_id
    await library_service.revoke_license_grant(
        db,
        org_id=context.org.id,
        license_id=license_id,
        grant_id=grant_id,
    )


@router.get(
    "/{org_id}/licenses/{license_id}/grants",
    response_model=OrgLicenseGrantsResponse,
    summary="List organization license grants",
    description="List the current team and member allocations for one org License.",
)
async def list_org_license_grants(
    org_id: UUID,
    license_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgLicenseGrantsResponse:
    """Return the current grant rows for one org-owned License."""
    del org_id
    grants = await library_service.list_license_grants(
        db,
        org_id=context.org.id,
        license_id=license_id,
    )
    return OrgLicenseGrantsResponse(
        grants=[OrgLicenseGrantResponse.model_validate(grant) for grant in grants]
    )


@router.get(
    "/{org_id}/library",
    response_model=OrgLibraryResponse,
    summary="List one organization's shared library",
    description=(
        "Return the org-owned Licenses visible to the caller. Admins and owners "
        "see the full library; plain members see only granted Licenses."
    ),
)
async def list_org_library(
    org_id: UUID,
    context: OrgMemberCtx,
    db: DatabaseSession,
) -> OrgLibraryResponse:
    """Return the org shared library for the current member."""
    del org_id
    items = await library_service.list_org_library(
        db,
        org_id=context.org.id,
        member=context.member,
    )
    return OrgLibraryResponse(
        items=[
            OrgLibraryItem.model_validate(
                {**item.model_dump(), "grant_count": grant_count}
            )
            for item, grant_count in items
        ]
    )


@router.post(
    "/{org_id}/library/{license_id}/artifacts/{artifact_id}/download",
    response_model=ArtifactDownloadResponse,
    summary="Request an org library artifact download",
    description=(
        "Return a short-lived presigned URL for one Artifact covered by a "
        "granted org-owned License."
    ),
)
async def request_org_library_artifact_download(
    org_id: UUID,
    license_id: UUID,
    artifact_id: UUID,
    request: Request,
    context: OrgMemberCtx,
    db: DatabaseSession,
) -> ArtifactDownloadResponse:
    """Return a short-lived download URL for a granted org library Artifact."""
    del org_id
    return await library_service.request_org_artifact_download(
        db,
        org_id=context.org.id,
        license_id=license_id,
        artifact_id=artifact_id,
        member=context.member,
        ip_address=request.client.host if request.client else None,
    )


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
    "/received",
    response_model=MyInvitationsResponse,
    operation_id="list_received_invitations",
    summary="List invitations addressed to me",
    description=(
        "List live pending invitations sent to the authenticated user's "
        "email. Token-free; the invitee accepts or declines by invitation id."
    ),
)
async def list_received_invitations(
    user: CurrentUser,
    db: DatabaseSession,
) -> MyInvitationsResponse:
    """List the authenticated user's pending invitations."""
    return await service.list_received_invitations(db=db, user=user)


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
    "/{org_id}/legal-profile",
    response_model=OrgLegalProfileResponse,
    summary="Get the organization legal profile",
    description=(
        "Return the organization's shared legal identity used for invoicing and "
        "payout readiness. Org owner only."
    ),
)
async def get_legal_profile(
    org_id: UUID,
    context: OrgOwner,
    db: DatabaseSession,
) -> OrgLegalProfileResponse:
    """Return the shared legal profile for one organization owner."""
    del context
    profile = await legal_profile_service.get_legal_profile(db, org_id=org_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization legal profile not found.",
        )
    return _legal_profile_response(profile)


@router.put(
    "/{org_id}/legal-profile",
    response_model=OrgLegalProfileResponse,
    summary="Upsert the organization legal profile",
    description=(
        "Create or update the organization's shared legal identity after an "
        "owner TOTP step-up. Org owner only."
    ),
)
async def upsert_legal_profile(
    org_id: UUID,
    payload: OrgLegalProfileUpdateRequest,
    context: OrgOwner,
    db: DatabaseSession,
    redis: RedisClient,
) -> OrgLegalProfileResponse:
    """Create or update the shared legal profile for one organization."""
    profile = await legal_profile_service.upsert_legal_profile(
        db,
        redis,
        org_id=org_id,
        actor_id=context.user.id,
        totp_code=payload.totp_code,
        legal_name=payload.legal_name,
        registration_number=payload.registration_number,
        address=payload.address,
    )
    return _legal_profile_response(profile)


@router.post(
    "/{org_id}/legal-profile/tax-document",
    response_model=CredentialEvidenceUploadSessionResponse,
    summary="Create an organization legal-profile tax-document upload session",
    description=(
        "Create a presigned upload session for the organization's shared legal "
        "profile tax document. Org owner only."
    ),
)
async def set_legal_profile_tax_document(
    org_id: UUID,
    payload: OrgAttestorTaxDocumentRequest,
    context: OrgOwner,
    db: DatabaseSession,
) -> CredentialEvidenceUploadSessionResponse:
    """Create a presigned upload session for the org legal-profile tax document."""
    return await legal_profile_service.set_tax_document(
        db,
        org_id=org_id,
        actor_id=context.user.id,
        payload=payload,
    )


@router.get(
    "/{org_id}/financials/earnings",
    response_model=EarningsResponse,
    summary="Organization earnings",
    description=(
        "Released organization earnings and available payout balance across "
        "supported commercial capabilities. Owner/admin only."
    ),
)
async def get_org_earnings(
    org_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> EarningsResponse:
    """Return the org's released earnings balances."""
    del context
    return await financials_service.get_org_earnings(db, org_id=org_id)


@router.post(
    "/{org_id}/financials/payment-methods/setup",
    response_model=OrgPaymentMethodSetupResponse,
    summary="Start organization payment-method setup",
    description=(
        "Create or reuse the organization's Stripe customer and return a "
        "SetupIntent client secret. TOTP-gated; owner/admin only."
    ),
)
async def create_org_payment_method_setup(
    org_id: UUID,
    payload: OrgPaymentMethodSetupRequest,
    context: OrgAdmin,
    db: DatabaseSession,
    redis: RedisClient,
) -> OrgPaymentMethodSetupResponse:
    """Create an organization payment-method SetupIntent after TOTP step-up."""
    await ORG_PAYMENT_METHOD_SETUP_RATE_LIMITER.check(
        cast(RedisCounter, redis), str(org_id)
    )
    response = await billing_service.create_org_payment_method_setup(
        db,
        redis,
        org_id=org_id,
        actor=context.user,
        totp_code=payload.totp_code,
    )
    return OrgPaymentMethodSetupResponse(**response.model_dump())


@router.get(
    "/{org_id}/financials/payment-methods",
    response_model=OrgPaymentMethodsResponse,
    summary="List organization payment methods",
    description=(
        "List the organization's saved provider-held payment methods using "
        "safe card metadata only. Owner/admin only."
    ),
)
async def list_org_payment_methods(
    org_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgPaymentMethodsResponse:
    """List safe organization payment-method metadata for org admins."""
    del context
    response = await billing_service.list_org_payment_methods(db, org_id=org_id)
    return OrgPaymentMethodsResponse(
        payment_methods=[
            OrgPaymentMethodResponse(**payment_method.model_dump())
            for payment_method in response.payment_methods
        ]
    )


@router.delete(
    "/{org_id}/financials/payment-methods/{payment_method_id}",
    response_model=OrgPaymentMethodDeleteResponse,
    summary="Remove an organization payment method",
    description=(
        "Detach a provider-held payment method from the organization after "
        "TOTP verification. Owner/admin only."
    ),
)
async def delete_org_payment_method(
    org_id: UUID,
    payment_method_id: str,
    payload: OrgPaymentMethodDeleteRequest,
    context: OrgAdmin,
    db: DatabaseSession,
    redis: RedisClient,
) -> OrgPaymentMethodDeleteResponse:
    """Detach one organization payment method after TOTP and ownership checks."""
    response = await billing_service.delete_org_payment_method(
        db,
        redis,
        org_id=org_id,
        actor=context.user,
        payment_method_id=payment_method_id,
        totp_code=payload.totp_code,
    )
    return OrgPaymentMethodDeleteResponse(**response.model_dump())


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
        "Request a payout of the org's available earnings. TOTP-gated "
        "(requester's own TOTP); requires a verified org payout account and "
        "an eligible active capability path. Owner/admin only."
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
        "List invoices issued for the organization's settled work. "
        "Non-sensitive metadata only. Owner/admin only."
    ),
)
async def list_org_invoices(
    org_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgInvoicesResponse:
    """List issued invoices for the org's settled work."""
    del context
    return await financials_service.list_org_invoices(db, org_id=org_id)


@router.get(
    "/{org_id}/financials/purchases/{transaction_id}/invoice",
    summary="Organization purchase invoice",
    description=(
        "Issue (lazily) and return the invoice for a Framework the organization "
        "purchased, addressed to the organization as buyer. Redirects to a "
        "presigned PDF URL once generated, otherwise queues generation. A "
        "billing record, available to owner/admins regardless of operator "
        "capability state."
    ),
)
async def get_org_purchase_invoice(
    org_id: UUID,
    transaction_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> Response:
    """Redirect to the org purchase invoice PDF or queue its generation."""
    del context
    return await financials_service.get_org_framework_purchase_invoice(
        db,
        org_id=org_id,
        transaction_id=transaction_id,
    )


@router.post(
    "/{org_id}/frameworks/{framework_id}/purchase",
    response_model=PurchaseResponse,
    summary="Purchase a Framework as an organization",
    description=(
        "Start Stripe checkout for a Framework purchased on behalf of the "
        "organization. The resulting License is owned by the organization. "
        "Requires an active Operator capability and a payment method on "
        "file. Owner/admin only."
    ),
)
async def create_org_framework_purchase(
    org_id: UUID,
    framework_id: UUID,
    payload: PurchaseRequest,
    context: OrgAdmin,
    _: Annotated[None, Depends(require_org_capability("operator"))],
    db: DatabaseSession,
    redis: RedisClient,
) -> PurchaseResponse:
    """Start org-payer Stripe checkout for one Framework."""
    await ORG_FRAMEWORK_PURCHASE_RATE_LIMITER.check(
        cast(RedisCounter, redis), str(org_id)
    )
    return await financials_service.create_org_framework_purchase(
        db,
        org_id=org_id,
        actor=context.user,
        framework_id=framework_id,
        payload=payload,
    )


@router.post(
    "/{org_id}/frameworks/{framework_id}/review",
    response_model=FrameworkReviewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Review a Framework as an organization",
    description=(
        "Write one public Framework review under the organization identity. "
        "Requires org admin/owner access, an active operator capability, and "
        "an active org-owned License for the Framework."
    ),
)
async def create_org_framework_review(
    org_id: UUID,
    framework_id: UUID,
    payload: FrameworkReviewCreate,
    context: OrgAdmin,
    _: Annotated[None, Depends(require_org_capability("operator"))],
    db: DatabaseSession,
) -> FrameworkReviewResponse:
    """Create one org-authored review for a licensed Framework."""
    return await frameworks_service.create_org_framework_review(
        db,
        org_id=org_id,
        actor=context.user,
        reviewing_member_id=context.member.id,
        framework_id=framework_id,
        payload=payload,
    )


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


@admin_orgs_router.post(
    "/{org_id}/contributor-capability/suspend",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Suspend an org's contributor capability (platform admin)",
    description=(
        "Suspend an org's contributor capability; member derived contributor "
        "roles are re-evaluated."
    ),
)
async def admin_suspend_contributor_capability(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> None:
    """Suspend an org's contributor capability."""
    await contributor_service.admin_set_contributor_capability_status(
        db, org_id=org_id, admin_id=admin.id, status_value="suspended"
    )


@admin_orgs_router.post(
    "/{org_id}/contributor-capability/reinstate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reinstate an org's contributor capability (platform admin)",
    description=(
        "Reactivate a suspended org contributor capability and re-grant any "
        "derived contributor roles."
    ),
)
async def admin_reinstate_contributor_capability(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> None:
    """Reinstate an org's contributor capability."""
    await contributor_service.admin_set_contributor_capability_status(
        db, org_id=org_id, admin_id=admin.id, status_value="active"
    )


@admin_orgs_router.post(
    "/{org_id}/contributor-capability/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an org's contributor capability (platform admin)",
    description=(
        "Revoke an org's contributor capability, deactivate its profile, and "
        "remove derived contributor roles from its members."
    ),
)
async def admin_revoke_contributor_capability(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> None:
    """Revoke an org's contributor capability."""
    await contributor_service.admin_set_contributor_capability_status(
        db, org_id=org_id, admin_id=admin.id, status_value="revoked"
    )


@admin_orgs_router.post(
    "/{org_id}/operator-capability/suspend",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Suspend an org's operator capability (platform admin)",
    description=(
        "Suspend an org's operator capability and remove derived operator "
        "roles from its members."
    ),
)
async def admin_suspend_operator_capability(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> None:
    """Suspend an org's operator capability."""
    await operator_service.admin_set_operator_capability_status(
        db, org_id=org_id, admin_id=admin.id, status_value="suspended"
    )


@admin_orgs_router.post(
    "/{org_id}/operator-capability/reinstate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reinstate an org's operator capability (platform admin)",
    description=(
        "Reactivate a suspended org operator capability and re-grant any "
        "derived operator roles."
    ),
)
async def admin_reinstate_operator_capability(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> None:
    """Reinstate an org's operator capability."""
    await operator_service.admin_set_operator_capability_status(
        db, org_id=org_id, admin_id=admin.id, status_value="active"
    )


@admin_orgs_router.post(
    "/{org_id}/operator-capability/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an org's operator capability (platform admin)",
    description=(
        "Revoke an org's operator capability and remove derived operator "
        "roles from its members."
    ),
)
async def admin_revoke_operator_capability(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> None:
    """Revoke an org's operator capability."""
    await operator_service.admin_set_operator_capability_status(
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
