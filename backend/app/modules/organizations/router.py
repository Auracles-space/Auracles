"""FastAPI router for Organizations Core endpoints."""

from __future__ import annotations

from typing import Annotated, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    get_current_user,
    require_role,
    require_step_up_after,
)
from app.core.rate_limit import RateLimiter, RedisCounter
from app.core.redis import get_redis
from app.modules.attestation import clarification_service, matching_service
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
from app.modules.frameworks.models import Framework
from app.modules.frameworks.schemas import (
    FrameworkReviewCreate,
    FrameworkReviewResponse,
)
from app.modules.library.schemas import ArtifactDownloadResponse
from app.modules.organizations import (
    attestor_application_service,
    attestor_trial_service,
    billing_service,
    contributor_directory_service,
    contributor_service,
    kyb_service,
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
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgLegalProfile,
    OrgMember,
)
from app.modules.organizations.schemas import (
    AdminOrgsResponse,
    AdminStartTrialRequest,
    AdminTrialGradeResponse,
    CalibrationFixtureItem,
    CalibrationFixturesResponse,
    ContributorOrgDirectoryEntry,
    ContributorOrgDirectoryResponse,
    CreateCalibrationFixtureRequest,
    FixtureArtifactConfirmRequest,
    FixtureArtifactItem,
    FixtureArtifactsResponse,
    FixtureArtifactUploadUrlRequest,
    FixtureArtifactUploadUrlResponse,
    LogoConfirmRequest,
    LogoUploadUrlRequest,
    LogoUploadUrlResponse,
    MemberSearchResponse,
    MyInvitationsResponse,
    MyOrganizationResponse,
    MyOrganizationsResponse,
    NomineeTrialResponse,
    OrgAcceptOfferRequest,
    OrgActionCounts,
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
    OrgAttestorDocumentsResponse,
    OrgAttestorFeedbackRequest,
    OrgAttestorGateChecklist,
    OrgAttestorIncorporationDocumentDeleteRequest,
    OrgAttestorIncorporationDocumentRequest,
    OrgAttestorTaxDocumentRequest,
    OrgCapabilityName,
    OrgCapabilityResponse,
    OrgInvitationCreateRequest,
    OrgInvitationPreviewResponse,
    OrgInvitationResponse,
    OrgInvitationsResponse,
    OrgKybReviewRequest,
    OrgKybStatusResponse,
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
    OrgStatusReasonRequest,
    OrgTeamCreateRequest,
    OrgTeamMembersResponse,
    OrgTeamRenameRequest,
    OrgTeamResponse,
    OrgTeamsResponse,
    OrgUndertakingsSignRequest,
    PublicOrganizationResponse,
    TrialAnswerKeysResponse,
    TrialDecideRequest,
    TrialSubmitRequest,
    UpsertTrialAnswerKeyRequest,
)

router = APIRouter(prefix="/orgs", tags=["Organizations"])
public_router = APIRouter(prefix="/contributors", tags=["Organizations"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
RedisClient = Annotated[Redis, Depends(get_redis)]
# Unverified organizations reach only the routes that lead out of the shell:
# verification itself, the legal profile it checks, the org's own profile, and
# reads. Everything else takes a Verified* context, so business verification is
# enforced once at the dependency layer rather than remembered per service.
OrgMemberCtx = Annotated[OrgContext, Depends(require_org_role("member"))]
OrgAdmin = Annotated[OrgContext, Depends(require_org_role("admin"))]
OrgOwner = Annotated[OrgContext, Depends(require_org_role("owner"))]
VerifiedOrgMemberCtx = Annotated[
    OrgContext, Depends(require_org_role("member", verified=True))
]
VerifiedOrgAdmin = Annotated[
    OrgContext, Depends(require_org_role("admin", verified=True))
]
VerifiedOrgOwner = Annotated[
    OrgContext, Depends(require_org_role("owner", verified=True))
]

# Every organization created needs an admin to verify it before it can do
# anything, so unbounded creation floods the review queue. A day's allowance is
# well above what a real operator needs and well below what makes flooding
# worthwhile.
ORG_CREATE_LIMIT = 5
ORG_CREATE_RATE_LIMITER = RateLimiter(
    namespace="org_create", limit=ORG_CREATE_LIMIT, window=86400
)
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
    trial: tuple[str, str | None] | None = None,
) -> OrgAttestorApplicationResponse:
    """Assemble the application response with its derived gate checklist."""
    return OrgAttestorApplicationResponse(
        trial_status=trial[0] if trial else None,
        trial_feedback=trial[1] if trial else None,
        id=application.id,
        org_id=application.org_id,
        status=application.status,
        sectors=application.sectors,
        functions=application.functions,
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
    redis: RedisClient,
) -> OrganizationResponse:
    """Create an organization for the authenticated user."""
    await ORG_CREATE_RATE_LIMITER.check(cast(RedisCounter, redis), str(user.id))
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
    admin_org_ids = [
        organization.id
        for organization, role, _caps in organizations
        if role in {"owner", "admin"}
    ]
    # Non-admin members get a queue count scoped to their own assignments, so
    # resolve this user's membership id in each such org.
    member_org_ids = [
        organization.id
        for organization, role, _caps in organizations
        if role not in {"owner", "admin"}
    ]
    member_queue_scope: dict[UUID, UUID] = {}
    if member_org_ids:
        member_rows = await db.execute(
            select(OrgMember.org_id, OrgMember.id).where(
                OrgMember.user_id == user.id,
                OrgMember.org_id.in_(member_org_ids),
            )
        )
        member_queue_scope = {org_id: mid for org_id, mid in member_rows.all()}
    counts_by_org = await service.count_org_actions(
        db,
        admin_org_ids=admin_org_ids,
        member_queue_scope=member_queue_scope,
    )
    org_ids = [organization.id for organization, _role, _caps in organizations]
    grants_by_org = await service.caller_capability_grants(
        db,
        user_id=user.id,
        org_ids=org_ids,
    )
    kyb_by_org = {
        org_id: kyb_status
        for org_id, kyb_status in (
            await db.execute(
                select(OrgLegalProfile.org_id, OrgLegalProfile.kyb_status).where(
                    OrgLegalProfile.org_id.in_(org_ids)
                )
            )
        ).all()
    }
    return MyOrganizationsResponse(
        organizations=[
            MyOrganizationResponse(
                org=OrganizationResponse.model_validate(organization),
                role=role,
                capabilities={
                    capability.capability: capability.status
                    for capability in capabilities
                },
                capability_reasons={
                    capability.capability: capability.status_reason
                    for capability in capabilities
                    if capability.status_reason
                },
                grants={
                    capability: True
                    for capability in grants_by_org.get(organization.id, set())
                },
                counts=counts_by_org.get(organization.id, OrgActionCounts()),
                kyb_status=kyb_by_org.get(organization.id, "unverified"),
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
    context: VerifiedOrgMemberCtx,
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
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgAdmin,
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
    description=("Allocate one org-owned License to exactly one team or one member."),
)
async def add_org_license_grant(
    org_id: UUID,
    license_id: UUID,
    payload: OrgLicenseGrantRequest,
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgMemberCtx,
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
    context: VerifiedOrgMemberCtx,
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
    context: VerifiedOrgMemberCtx,
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
    context: VerifiedOrgOwner,
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
        "Transfer ownership to another existing member. Requires an open "
        "step-up 2FA window. Org owner only."
    ),
    dependencies=[Depends(require_step_up_after(require_org_role("owner")))],
)
async def transfer_ownership(
    org_id: UUID,
    payload: OrgOwnershipTransferRequest,
    context: VerifiedOrgOwner,
    db: DatabaseSession,
) -> None:
    """Transfer organization ownership to another member."""
    del org_id
    await service.transfer_ownership(
        db=db,
        context=context,
        new_owner_member_id=payload.new_owner_member_id,
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
    context: VerifiedOrgAdmin,
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
    "/{org_id}/member-search",
    response_model=MemberSearchResponse,
    operation_id="search_org_members",
    summary="Search existing users to invite",
    description=(
        "Admin-only invite typeahead. Prefix-matches existing users by email "
        "or display name and returns masked emails only."
    ),
)
async def search_org_members(
    org_id: UUID,
    q: str,
    context: VerifiedOrgAdmin,
    db: DatabaseSession,
    redis: RedisClient,
) -> MemberSearchResponse:
    """Return masked invite suggestions for an organization admin."""
    del org_id
    return await service.search_members(db=db, redis=redis, context=context, q=q)


@router.get(
    "/{org_id}/invitations",
    response_model=OrgInvitationsResponse,
    summary="List pending organization invitations",
    description="List pending invitations for one organization.",
)
async def list_invitations(
    org_id: UUID,
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgMemberCtx,
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
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgAdmin,
    db: DatabaseSession,
) -> None:
    """Delete a team in the organization."""
    del org_id
    await service.delete_team(db=db, context=context, team_id=team_id)


@router.get(
    "/{org_id}/teams/{team_id}/members",
    response_model=OrgTeamMembersResponse,
    summary="List team members",
    description="List the organization members that belong to one team.",
)
async def list_team_members(
    org_id: UUID,
    team_id: UUID,
    context: VerifiedOrgMemberCtx,
    db: DatabaseSession,
) -> OrgTeamMembersResponse:
    """List the members of one team."""
    del org_id
    return await service.list_team_members(db=db, context=context, team_id=team_id)


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
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgAdmin,
    db: DatabaseSession,
) -> None:
    """Remove a member from a team."""
    del org_id
    await service.remove_team_member(
        db=db, context=context, team_id=team_id, member_id=member_id
    )


@router.put(
    "/{org_id}/teams/{team_id}/capabilities/{capability}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Enable a capability on a team",
    description=(
        "Grant a marketplace capability to every member of a team. Requires "
        "the org capability to already be active. Owner/admin only."
    ),
)
async def enable_team_capability(
    org_id: UUID,
    team_id: UUID,
    capability: OrgCapabilityName,
    context: VerifiedOrgAdmin,
    db: DatabaseSession,
) -> None:
    """Enable one marketplace capability on a team."""
    del org_id
    await service.enable_team_capability(
        db=db,
        context=context,
        team_id=team_id,
        capability=capability,
    )


@router.delete(
    "/{org_id}/teams/{team_id}/capabilities/{capability}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disable a capability on a team",
    description="Revoke a marketplace capability from a team. Owner/admin only.",
)
async def disable_team_capability(
    org_id: UUID,
    team_id: UUID,
    capability: OrgCapabilityName,
    context: VerifiedOrgAdmin,
    db: DatabaseSession,
) -> None:
    """Disable one marketplace capability on a team."""
    del org_id
    await service.disable_team_capability(
        db=db,
        context=context,
        team_id=team_id,
        capability=capability,
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
    context: VerifiedOrgMemberCtx,
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
        document=nda_status.document,
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
    context: VerifiedOrgMemberCtx,
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
        document=nda_status.document,
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
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgAdmin,
    db: DatabaseSession,
) -> OrgAttestorApplicationResponse:
    """Return the org's attestor application with its gate checklist."""
    application, checklist = await attestor_application_service.get_application(
        db, org_id=org_id
    )
    trial = await attestor_application_service.latest_trial_outcome(
        db, application_id=application.id
    )
    return _application_response(application, checklist, trial)


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
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgAdmin,
    db: DatabaseSession,
    redis: RedisClient,
) -> OrgAttestorApplicationResponse:
    """Submit the org's attestor application for review."""
    await ORG_ATTESTOR_APPLY_RATE_LIMITER.check(cast(RedisCounter, redis), str(org_id))
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
        "Requires an open step-up 2FA window; org owner only."
    ),
    dependencies=[
        Depends(require_step_up_after(require_org_role("owner", verified=True)))
    ],
)
async def sign_attestor_undertakings(
    org_id: UUID,
    payload: OrgUndertakingsSignRequest,
    context: VerifiedOrgOwner,
    db: DatabaseSession,
) -> OrgAttestorApplicationResponse:
    """Owner-sign the org attestor undertakings."""
    await attestor_application_service.sign_undertakings(
        db, org_id=org_id, user=context.user, payload=payload
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
    context: VerifiedOrgAdmin,
    db: DatabaseSession,
) -> CredentialEvidenceUploadSessionResponse:
    """Create a presigned tax-document upload session for the application."""
    return await attestor_application_service.set_tax_document(
        db, org_id=org_id, actor_id=context.user.id, payload=payload
    )


async def _kyb_status_response(
    db: DatabaseSession,
    org_id: UUID,
    country: str,
) -> OrgKybStatusResponse:
    """Assemble the verification surface for one organization.

    Takes plain values rather than the ORM row: callers reach here after a
    service commit, which expires loaded instances, and touching an expired
    attribute would lazy-load outside the async greenlet.
    """
    profile = await legal_profile_service.get_legal_profile(db, org_id=org_id)
    if profile is None:
        return OrgKybStatusResponse(kyb_status="unverified", country=country)
    return OrgKybStatusResponse(
        kyb_status=profile.kyb_status,
        country=country,
        legal_name=profile.legal_name,
        registration_number=profile.registration_number,
        incorporation_doc_keys=profile.incorporation_doc_keys,
        kyb_submitted_at=profile.kyb_submitted_at,
        kyb_verified_at=profile.kyb_verified_at,
        kyb_review_notes=profile.kyb_review_notes,
    )


@router.get(
    "/{org_id}/kyb",
    response_model=OrgKybStatusResponse,
    summary="Get the organization's verification status",
    description=(
        "Return the organization's business-verification state and the legal "
        "identity under review. Any org member may read it."
    ),
)
async def get_org_kyb(
    org_id: UUID,
    context: OrgMemberCtx,
    db: DatabaseSession,
) -> OrgKybStatusResponse:
    """Return the org's business-verification state."""
    del org_id
    return await _kyb_status_response(db, context.org.id, context.org.country)


@router.post(
    "/{org_id}/kyb/incorporation-document",
    response_model=CredentialEvidenceUploadSessionResponse,
    summary="Create an incorporation-document upload session",
    description=(
        "Create a presigned upload session for one incorporation document and "
        "attach its S3 key to the organization. Owner/admin only."
    ),
)
async def add_org_incorporation_document(
    org_id: UUID,
    payload: OrgAttestorIncorporationDocumentRequest,
    context: OrgAdmin,
    db: DatabaseSession,
) -> CredentialEvidenceUploadSessionResponse:
    """Create a presigned incorporation-document upload session."""
    del org_id
    target = await kyb_service.add_incorporation_document(
        db,
        org_id=context.org.id,
        actor_id=context.user.id,
        file_name=payload.file_name,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
    )
    return CredentialEvidenceUploadSessionResponse(
        id=uuid4(),
        s3_key=target.s3_key,
        url=target.url,
        fields=target.fields,
        expires_at=target.expires_at,
        size_limit=kyb_service.INCORPORATION_DOC_MAX_BYTES,
        scan_status="pending_scan",
    )


@router.delete(
    "/{org_id}/kyb/incorporation-document",
    response_model=OrgKybStatusResponse,
    summary="Remove an incorporation document",
    description=(
        "Detach one incorporation document from the organization by its S3 "
        "key. Owner/admin only, and refused once verified."
    ),
)
async def remove_org_incorporation_document(
    org_id: UUID,
    payload: OrgAttestorIncorporationDocumentDeleteRequest,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgKybStatusResponse:
    """Detach one incorporation document from the organization."""
    del org_id
    resolved_id, country = context.org.id, context.org.country
    await kyb_service.remove_incorporation_document(
        db, org_id=resolved_id, actor_id=context.user.id, s3_key=payload.s3_key
    )
    return await _kyb_status_response(db, resolved_id, country)


@router.post(
    "/{org_id}/kyb/submit",
    response_model=OrgKybStatusResponse,
    summary="Submit the organization for verification",
    description=(
        "Send the organization's legal details and incorporation documents "
        "for admin review. Owner/admin only."
    ),
)
async def submit_org_kyb(
    org_id: UUID,
    context: OrgAdmin,
    db: DatabaseSession,
) -> OrgKybStatusResponse:
    """Submit the organization's business details for verification."""
    del org_id
    resolved_id, country = context.org.id, context.org.country
    await kyb_service.submit_for_verification(
        db, org_id=resolved_id, actor_id=context.user.id
    )
    return await _kyb_status_response(db, resolved_id, country)


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
    context: VerifiedOrgAdmin,
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


@router.get(
    "/{org_id}/attestor-trial",
    response_model=NomineeTrialResponse,
    summary="Load the nominee calibration trial",
    description=(
        "Return the nominated member's active calibration trial, including the "
        "fixture, rubric, and any saved scores."
    ),
)
async def get_attestor_trial(
    org_id: UUID,
    context: VerifiedOrgMemberCtx,
    db: DatabaseSession,
) -> NomineeTrialResponse:
    """Return the nominated member's live calibration trial."""
    return await attestor_trial_service.load_nominee_trial(
        db,
        org_id=org_id,
        member=context.member,
    )


@router.post(
    "/{org_id}/attestor-trial/submit",
    response_model=NomineeTrialResponse,
    summary="Submit the nominee calibration trial",
    description=(
        "Persist the nominee's rubric scores and auto-score the active "
        "calibration trial."
    ),
)
async def submit_attestor_trial(
    org_id: UUID,
    payload: TrialSubmitRequest,
    context: VerifiedOrgMemberCtx,
    db: DatabaseSession,
) -> NomineeTrialResponse:
    """Submit the nominee's rubric for the active calibration trial."""
    return await attestor_trial_service.submit_nominee_trial(
        db,
        org_id=org_id,
        member=context.member,
        payload=payload,
    )


def _offer_item(
    offer: AttestationOffer,
    attestation: Attestation,
    target_title: str | None = None,
) -> OrgAttestationOfferItem:
    """Build an offer list item from an offer + attestation pair."""
    return OrgAttestationOfferItem(
        offer_id=offer.id,
        attestation_id=attestation.id,
        target_type=attestation.target_type,
        target_id=attestation.target_id,
        target_title=target_title,
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
    context: VerifiedOrgAdmin,
    db: DatabaseSession,
) -> OrgAttestationOffersResponse:
    """List cohort offers made to the attestor org."""
    del context
    rows = await matching_service.list_org_offers(db, org_id=org_id)
    # Resolve framework titles in one query so each offer card can preview the
    # asset name instead of a bare "framework" label.
    framework_ids = {
        attestation.target_id
        for _offer, attestation in rows
        if attestation.target_type == "framework"
    }
    titles: dict[UUID, str] = {}
    if framework_ids:
        title_rows = await db.execute(
            select(Framework.id, Framework.title).where(Framework.id.in_(framework_ids))
        )
        titles = {fid: title for fid, title in title_rows.all()}
    return OrgAttestationOffersResponse(
        offers=[
            _offer_item(
                offer,
                attestation,
                titles.get(attestation.target_id)
                if attestation.target_type == "framework"
                else None,
            )
            for offer, attestation in rows
        ]
    )


@router.post(
    "/{org_id}/attestation-offers/{offer_id}/accept",
    response_model=OrgAttestationItem,
    summary="Accept and staff an offer",
    description=(
        "Accept a cohort offer and staff it with a reviewing member. Owner/admin only."
    ),
)
async def accept_org_attestation_offer(
    org_id: UUID,
    offer_id: UUID,
    payload: OrgAcceptOfferRequest,
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgMemberCtx,
    db: DatabaseSession,
) -> OrgAttestationsResponse:
    """List the org's attestations, scoped by the caller's role."""
    caller_member_id = context.member.id
    reviewing_member_id = (
        None if context.member.role in ("owner", "admin") else context.member.id
    )
    rows = await matching_service.list_org_attestations(
        db,
        org_id=org_id,
        reviewing_member_id=reviewing_member_id,
    )
    # Resolve friendly labels so the queue shows a framework title and reviewer
    # name instead of raw UUIDs.
    framework_ids = {row.target_id for row in rows if row.target_type == "framework"}
    titles: dict[UUID, str] = {}
    if framework_ids:
        title_rows = await db.execute(
            select(Framework.id, Framework.title).where(Framework.id.in_(framework_ids))
        )
        titles = {fid: title for fid, title in title_rows.all()}
    member_ids = {row.reviewing_member_id for row in rows if row.reviewing_member_id}
    member_names: dict[UUID, str] = {}
    if member_ids:
        member_rows = await db.execute(
            select(OrgMember.id, User.display_name)
            .join(User, User.id == OrgMember.user_id)
            .where(OrgMember.id.in_(member_ids))
        )
        member_names = {mid: name for mid, name in member_rows.all()}
    unread_answer_ids = await clarification_service.unread_answer_attestation_ids(
        db, [row.id for row in rows]
    )
    return OrgAttestationsResponse(
        attestations=[
            OrgAttestationItem(
                id=row.id,
                target_type=row.target_type,
                target_id=row.target_id,
                target_title=titles.get(row.target_id)
                if row.target_type == "framework"
                else None,
                review_type=row.review_type,
                status=row.status,
                outcome=row.outcome,
                reviewing_member_id=row.reviewing_member_id,
                reviewing_member_name=member_names.get(row.reviewing_member_id)
                if row.reviewing_member_id
                else None,
                assigned_to_me=row.reviewing_member_id == caller_member_id,
                accepted_at=row.accepted_at,
                completion_due_at=row.completion_due_at,
                updated_at=row.updated_at,
                unread_answer=row.id in unread_answer_ids,
            )
            for row in rows
        ]
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


@invitation_router.post(
    "/received/{invitation_id}/accept",
    response_model=MyOrganizationResponse,
    operation_id="accept_received_invitation",
    summary="Accept an invitation from my inbox",
    description=(
        "Accept a pending invitation by id. The caller's email must match "
        "the invitation."
    ),
)
async def accept_received_invitation(
    invitation_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
) -> MyOrganizationResponse:
    """Accept an invitation addressed to the authenticated user by id."""
    return await service.accept_invitation_by_id(
        db=db,
        user=user,
        invitation_id=invitation_id,
    )


@invitation_router.post(
    "/received/{invitation_id}/decline",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="decline_received_invitation",
    summary="Decline an invitation from my inbox",
    description=(
        "Decline a pending invitation by id. The caller's email must match "
        "the invitation."
    ),
)
async def decline_received_invitation(
    invitation_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
) -> None:
    """Decline an invitation addressed to the authenticated user by id."""
    await service.decline_invitation_by_id(
        db=db,
        user=user,
        invitation_id=invitation_id,
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
        "Create or update the organization's shared legal identity. Requires "
        "an open step-up 2FA window. Org owner only."
    ),
    dependencies=[Depends(require_step_up_after(require_org_role("owner")))],
)
async def upsert_legal_profile(
    org_id: UUID,
    payload: OrgLegalProfileUpdateRequest,
    context: OrgOwner,
    db: DatabaseSession,
) -> OrgLegalProfileResponse:
    """Create or update the shared legal profile for one organization."""
    profile = await legal_profile_service.upsert_legal_profile(
        db,
        org_id=org_id,
        actor_id=context.user.id,
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
    context: VerifiedOrgAdmin,
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
        "SetupIntent client secret. Requires an open step-up 2FA window; "
        "owner/admin only."
    ),
    dependencies=[
        Depends(require_step_up_after(require_org_role("admin", verified=True)))
    ],
)
async def create_org_payment_method_setup(
    org_id: UUID,
    payload: OrgPaymentMethodSetupRequest,
    context: VerifiedOrgAdmin,
    db: DatabaseSession,
    redis: RedisClient,
) -> OrgPaymentMethodSetupResponse:
    """Create an organization payment-method SetupIntent inside a step-up window."""
    del payload
    await ORG_PAYMENT_METHOD_SETUP_RATE_LIMITER.check(
        cast(RedisCounter, redis), str(org_id)
    )
    response = await billing_service.create_org_payment_method_setup(
        db,
        org_id=org_id,
        actor=context.user,
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
    context: VerifiedOrgAdmin,
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
        "Detach a provider-held payment method from the organization. "
        "Requires an open step-up 2FA window. Owner/admin only."
    ),
    dependencies=[
        Depends(require_step_up_after(require_org_role("admin", verified=True)))
    ],
)
async def delete_org_payment_method(
    org_id: UUID,
    payment_method_id: str,
    payload: OrgPaymentMethodDeleteRequest,
    context: VerifiedOrgAdmin,
    db: DatabaseSession,
) -> OrgPaymentMethodDeleteResponse:
    """Detach one organization payment method after the ownership check."""
    del payload
    response = await billing_service.delete_org_payment_method(
        db,
        org_id=org_id,
        actor=context.user,
        payment_method_id=payment_method_id,
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
    context: VerifiedOrgAdmin,
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
        "Request a payout of the org's available earnings. Requires an open "
        "step-up 2FA window, a verified org payout account and an eligible "
        "active capability path. Owner/admin only."
    ),
    dependencies=[
        Depends(require_step_up_after(require_org_role("admin", verified=True)))
    ],
)
async def request_org_payout(
    org_id: UUID,
    payload: PayoutRequest,
    context: VerifiedOrgAdmin,
    db: DatabaseSession,
) -> PayoutResponse:
    """Request an org payout inside an open step-up window."""
    return await financials_service.request_org_payout(
        db, org_id=org_id, actor=context.user, payload=payload
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
    context: VerifiedOrgAdmin,
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
        "purchased, addressed to the organization as buyer. Returns a "
        "presigned PDF URL once generated, otherwise queues generation. A "
        "billing record, available to owner/admins regardless of operator "
        "capability state."
    ),
)
async def get_org_purchase_invoice(
    org_id: UUID,
    transaction_id: UUID,
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgAdmin,
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
    context: VerifiedOrgAdmin,
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


@admin_orgs_router.post(
    "/{org_id}/kyb/review",
    response_model=OrgKybStatusResponse,
    summary="Decide an organization's business verification",
    description=(
        "Record a verified/rejected verdict on an organization awaiting "
        "business verification. Verifying unlocks every capability, so the "
        "write requires an open step-up 2FA window. Rejection is not "
        "terminal: the organization may correct its details and submit again."
    ),
    dependencies=[Depends(require_step_up_after(require_role("admin")))],
)
async def admin_review_org_kyb(
    org_id: UUID,
    payload: OrgKybReviewRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> OrgKybStatusResponse:
    """Record an admin's business-verification decision for one org."""
    await kyb_service.review_org_kyb(
        db,
        org_id=org_id,
        admin_id=admin.id,
        verdict=payload.verdict,
        notes=payload.notes,
    )
    organization = await db.get(Organization, org_id)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )
    return await _kyb_status_response(db, org_id, organization.country)


@admin_orgs_router.get(
    "",
    response_model=AdminOrgsResponse,
    summary="List organizations (platform admin)",
    description=(
        "Paginated organization directory for platform administrators, with "
        "member counts, capability statuses, business verification, and "
        "slug/name search. Filter by kyb_status to read the pending-"
        "verification queue."
    ),
)
async def admin_list_orgs(
    admin: PlatformAdmin,
    db: DatabaseSession,
    query: str | None = Query(default=None, max_length=120),
    kyb_status: Literal["unverified", "pending", "verified", "rejected"] | None = Query(
        default=None
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AdminOrgsResponse:
    """List/search organizations for platform administration."""
    del admin
    return await service.admin_list_orgs(
        db=db, query=query, kyb_status=kyb_status, page=page, page_size=page_size
    )


@admin_orgs_router.post(
    "/{org_id}/suspend",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Suspend an organization (platform admin)",
    description=(
        "Suspend an organization platform-wide. Idempotent; members lose "
        "org access and derived roles are re-evaluated."
    ),
    dependencies=[Depends(require_step_up_after(require_role("admin")))],
)
async def admin_suspend_org(
    org_id: UUID,
    payload: OrgStatusReasonRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> None:
    """Suspend an organization platform-wide (idempotent), recording why."""
    await service.admin_suspend_org(
        db=db, admin=admin, org_id=org_id, reason=payload.reason
    )


@admin_orgs_router.post(
    "/{org_id}/reinstate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reinstate a suspended organization (platform admin)",
    description=(
        "Lift a platform-wide organization suspension. Idempotent; members "
        "regain org access and derived roles are re-evaluated."
    ),
    dependencies=[Depends(require_step_up_after(require_role("admin")))],
)
async def admin_reinstate_org(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> None:
    """Reinstate a suspended organization platform-wide (idempotent)."""
    await service.admin_reinstate_org(db=db, admin=admin, org_id=org_id)


@admin_orgs_router.post(
    "/{org_id}/attestor-capability/suspend",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Suspend an org's attestor capability (platform admin)",
    description=(
        "Suspend an org's attestor capability; the profile is retained but "
        "excluded from matching and members' derived roles are re-evaluated."
    ),
    dependencies=[Depends(require_step_up_after(require_role("admin")))],
)
async def admin_suspend_attestor_capability(
    org_id: UUID,
    payload: OrgStatusReasonRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> None:
    """Suspend an org's attestor capability."""
    await attestor_application_service.admin_set_capability_status(
        db,
        org_id=org_id,
        admin_id=admin.id,
        status_value="suspended",
        reason=payload.reason,
    )


@admin_orgs_router.post(
    "/{org_id}/attestor-capability/reinstate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reinstate an org's attestor capability (platform admin)",
    description=(
        "Reactivate a suspended org attestor capability and its profile; "
        "members' derived roles are re-evaluated."
    ),
    dependencies=[Depends(require_step_up_after(require_role("admin")))],
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
    dependencies=[Depends(require_step_up_after(require_role("admin")))],
)
async def admin_revoke_attestor_capability(
    org_id: UUID,
    payload: OrgStatusReasonRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> None:
    """Revoke an org's attestor capability."""
    await attestor_application_service.admin_set_capability_status(
        db,
        org_id=org_id,
        admin_id=admin.id,
        status_value="revoked",
        reason=payload.reason,
    )


@admin_orgs_router.post(
    "/{org_id}/contributor-capability/suspend",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Suspend an org's contributor capability (platform admin)",
    description=(
        "Suspend an org's contributor capability; member derived contributor "
        "roles are re-evaluated."
    ),
    dependencies=[Depends(require_step_up_after(require_role("admin")))],
)
async def admin_suspend_contributor_capability(
    org_id: UUID,
    payload: OrgStatusReasonRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> None:
    """Suspend an org's contributor capability."""
    await contributor_service.admin_set_contributor_capability_status(
        db,
        org_id=org_id,
        admin_id=admin.id,
        status_value="suspended",
        reason=payload.reason,
    )


@admin_orgs_router.post(
    "/{org_id}/contributor-capability/reinstate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reinstate an org's contributor capability (platform admin)",
    description=(
        "Reactivate a suspended org contributor capability and re-grant any "
        "derived contributor roles."
    ),
    dependencies=[Depends(require_step_up_after(require_role("admin")))],
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
    dependencies=[Depends(require_step_up_after(require_role("admin")))],
)
async def admin_revoke_contributor_capability(
    org_id: UUID,
    payload: OrgStatusReasonRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> None:
    """Revoke an org's contributor capability."""
    await contributor_service.admin_set_contributor_capability_status(
        db,
        org_id=org_id,
        admin_id=admin.id,
        status_value="revoked",
        reason=payload.reason,
    )


@admin_orgs_router.post(
    "/{org_id}/operator-capability/suspend",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Suspend an org's operator capability (platform admin)",
    description=(
        "Suspend an org's operator capability and remove derived operator "
        "roles from its members."
    ),
    dependencies=[Depends(require_step_up_after(require_role("admin")))],
)
async def admin_suspend_operator_capability(
    org_id: UUID,
    payload: OrgStatusReasonRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> None:
    """Suspend an org's operator capability."""
    await operator_service.admin_set_operator_capability_status(
        db,
        org_id=org_id,
        admin_id=admin.id,
        status_value="suspended",
        reason=payload.reason,
    )


@admin_orgs_router.post(
    "/{org_id}/operator-capability/reinstate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reinstate an org's operator capability (platform admin)",
    description=(
        "Reactivate a suspended org operator capability and re-grant any "
        "derived operator roles."
    ),
    dependencies=[Depends(require_step_up_after(require_role("admin")))],
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
    dependencies=[Depends(require_step_up_after(require_role("admin")))],
)
async def admin_revoke_operator_capability(
    org_id: UUID,
    payload: OrgStatusReasonRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> None:
    """Revoke an org's operator capability."""
    await operator_service.admin_set_operator_capability_status(
        db,
        org_id=org_id,
        admin_id=admin.id,
        status_value="revoked",
        reason=payload.reason,
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
    trial_states = await attestor_application_service.admin_trial_states(
        db, [row.id for row in rows]
    )
    capability_states = await attestor_application_service.admin_capability_states(
        db, [row.org_id for row in rows]
    )
    org_identities = await attestor_application_service.admin_org_identities(
        db, [row.org_id for row in rows]
    )
    items: list[OrgAttestorAdminListItem] = []
    for row in rows:
        item = OrgAttestorAdminListItem.model_validate(row)
        item.trial_status = trial_states.get(row.id)
        item.capability_status = capability_states.get(row.org_id)
        org_name, kyb_status = org_identities.get(row.org_id, (None, "unverified"))
        item.org_name = org_name
        item.kyb_status = kyb_status
        items.append(item)
    return OrgAttestorAdminListResponse(
        applications=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@admin_org_attestor_router.get(
    "/{application_id}/documents",
    response_model=OrgAttestorDocumentsResponse,
    summary="List KYB/tax document links (platform admin)",
    description=(
        "Return short-lived presigned GET links for an application's "
        "incorporation and tax documents. Access is audited."
    ),
)
async def admin_list_org_attestor_documents(
    application_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> OrgAttestorDocumentsResponse:
    """Return presigned download links for an application's review documents."""
    documents = await attestor_application_service.admin_list_documents(
        db, application_id=application_id, admin_id=admin.id
    )
    return OrgAttestorDocumentsResponse(documents=documents)


# KYB is decided on the organization, not here. This queue used to stamp the
# KYB gate because an attestor application was the only place an org's legal
# identity was ever checked. Verification now precedes every capability, so the
# verdict is recorded once, on the organization, and this queue reads it.


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
    application, checklist = await attestor_application_service.get_application_by_id(
        db, application_id=application_id
    )
    return _admin_application_response(application, checklist)


@admin_org_attestor_router.post(
    "/{application_id}/start-trial",
    response_model=OrgAttestorApplicationResponse,
    summary="Start the calibration trial (platform admin)",
    description="Assign the calibration trial to the nominated org member.",
)
async def admin_start_trial(
    application_id: UUID,
    payload: AdminStartTrialRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> OrgAttestorApplicationResponse:
    """Assign the calibration trial to the nominated member."""
    await attestor_application_service.admin_start_trial(
        db,
        application_id=application_id,
        admin_id=admin.id,
        framework_id=payload.framework_id,
    )
    application, checklist = await attestor_application_service.get_application_by_id(
        db, application_id=application_id
    )
    return _admin_application_response(application, checklist)


@admin_org_attestor_router.get(
    "/{application_id}/trial",
    response_model=AdminTrialGradeResponse,
    summary="Load the calibration-trial grade view (platform admin)",
    description="Return the nominee submission beside the calibration answer key.",
)
async def admin_get_trial_grade(
    application_id: UUID,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> AdminTrialGradeResponse:
    """Return the latest trial grade view for one application."""
    del admin
    return await attestor_trial_service.admin_trial_grade(
        db,
        application_id=application_id,
    )


@admin_org_attestor_router.post(
    "/{application_id}/trial/decide",
    response_model=OrgAttestorApplicationResponse,
    summary="Decide the calibration trial (platform admin)",
    description="Confirm or override the latest submitted calibration trial.",
    dependencies=[Depends(require_step_up_after(require_role("admin")))],
)
async def admin_decide_trial(
    application_id: UUID,
    payload: TrialDecideRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> OrgAttestorApplicationResponse:
    """Confirm or override the submitted trial outcome."""
    await attestor_trial_service.admin_decide_trial(
        db,
        application_id=application_id,
        admin_id=admin.id,
        payload=payload,
    )
    application, checklist = await attestor_application_service.get_application_by_id(
        db,
        application_id=application_id,
    )
    return _admin_application_response(application, checklist)


@admin_org_attestor_router.get(
    "/calibration-fixtures",
    response_model=CalibrationFixturesResponse,
    summary="List calibration fixtures (platform admin)",
    description="Return platform calibration fixtures for the admin trial picker.",
)
async def admin_list_calibration_fixtures(
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> CalibrationFixturesResponse:
    """Return calibration fixtures available for trial assignment."""
    del admin
    return await attestor_trial_service.list_fixtures(db)


@admin_org_attestor_router.post(
    "/calibration-fixtures",
    response_model=CalibrationFixtureItem,
    status_code=status.HTTP_201_CREATED,
    summary="Create a calibration fixture (platform admin)",
    description="Create a new platform-owned calibration fixture shell.",
)
async def admin_create_calibration_fixture(
    payload: CreateCalibrationFixtureRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> CalibrationFixtureItem:
    """Create one calibration fixture for future trial assignment."""
    fixture = await attestor_trial_service.create_calibration_fixture(
        db,
        admin_id=admin.id,
        payload=payload,
    )
    return CalibrationFixtureItem(
        id=fixture.id,
        title=fixture.title,
        review_type=fixture.calibration_review_type or "",
    )


@admin_org_attestor_router.put(
    "/calibration-fixtures/{framework_id}/answer-key",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Upsert one fixture answer-key row (platform admin)",
    description="Create or update one expected rubric score for a calibration fixture.",
)
async def admin_upsert_trial_answer_key(
    framework_id: UUID,
    payload: UpsertTrialAnswerKeyRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> Response:
    """Create or update one answer-key row for a calibration fixture."""
    await attestor_trial_service.upsert_answer_key(
        db,
        framework_id=framework_id,
        admin_id=admin.id,
        payload=payload,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_org_attestor_router.get(
    "/calibration-fixtures/{framework_id}/answer-keys",
    response_model=TrialAnswerKeysResponse,
    summary="List a fixture's answer keys (platform admin)",
    description="Return every rubric dimension for a fixture with its key value.",
)
async def admin_list_trial_answer_keys(
    framework_id: UUID,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> TrialAnswerKeysResponse:
    """Return every rubric dimension for a fixture with its answer-key value."""
    del admin
    return await attestor_trial_service.list_answer_keys(db, framework_id=framework_id)


@admin_org_attestor_router.get(
    "/calibration-fixtures/{framework_id}/artifacts",
    response_model=FixtureArtifactsResponse,
    summary="List a fixture's artifacts (platform admin)",
    description="Return a calibration fixture's artifacts with scan state.",
)
async def admin_list_fixture_artifacts(
    framework_id: UUID,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> FixtureArtifactsResponse:
    """Return a calibration fixture's artifacts."""
    del admin
    return await attestor_trial_service.list_fixture_artifacts(
        db, framework_id=framework_id
    )


@admin_org_attestor_router.post(
    "/calibration-fixtures/{framework_id}/artifacts/upload-url",
    response_model=FixtureArtifactUploadUrlResponse,
    summary="Create a fixture-artifact upload target (platform admin)",
    description="Create a pending artifact row and a constrained S3 POST target.",
)
async def admin_create_fixture_artifact_upload_url(
    framework_id: UUID,
    payload: FixtureArtifactUploadUrlRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> FixtureArtifactUploadUrlResponse:
    """Create a presigned upload target for one fixture artifact."""
    return await attestor_trial_service.request_fixture_artifact_upload_url(
        db,
        framework_id=framework_id,
        admin_id=admin.id,
        payload=payload,
    )


@admin_org_attestor_router.post(
    "/calibration-fixtures/{framework_id}/artifacts/confirm",
    response_model=FixtureArtifactItem,
    summary="Confirm a fixture-artifact upload (platform admin)",
    description="Confirm the object exists in S3 and dispatch a virus scan.",
)
async def admin_confirm_fixture_artifact(
    framework_id: UUID,
    payload: FixtureArtifactConfirmRequest,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> FixtureArtifactItem:
    """Confirm a browser-uploaded fixture artifact and start scanning."""
    return await attestor_trial_service.confirm_fixture_artifact_upload(
        db,
        framework_id=framework_id,
        admin_id=admin.id,
        payload=payload,
    )


@admin_org_attestor_router.delete(
    "/calibration-fixtures/{framework_id}/artifacts/{artifact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a fixture artifact (platform admin)",
    description="Remove one fixture artifact row and its S3 object.",
)
async def admin_delete_fixture_artifact(
    framework_id: UUID,
    artifact_id: UUID,
    admin: PlatformAdmin,
    db: DatabaseSession,
) -> Response:
    """Delete one calibration fixture artifact."""
    await attestor_trial_service.delete_fixture_artifact(
        db,
        framework_id=framework_id,
        admin_id=admin.id,
        artifact_id=artifact_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_org_attestor_router.post(
    "/{application_id}/approve",
    response_model=OrgAttestorApplicationResponse,
    summary="Approve and activate (platform admin)",
    description=(
        "Approve a fully gated application: create the profile, activate the "
        "attestor capability, and grant every member the derived attestor role."
    ),
    dependencies=[Depends(require_step_up_after(require_role("admin")))],
)
async def admin_approve(
    application_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> OrgAttestorApplicationResponse:
    """Approve and activate an org attestor application."""
    await attestor_application_service.admin_approve(
        db, application_id=application_id, admin_id=admin.id
    )
    application, checklist = await attestor_application_service.get_application_by_id(
        db, application_id=application_id
    )
    return _admin_application_response(application, checklist)


@admin_org_attestor_router.post(
    "/{application_id}/reject",
    response_model=OrgAttestorApplicationResponse,
    summary="Reject an application (platform admin)",
    description="Terminally reject an application under review with feedback.",
    dependencies=[Depends(require_step_up_after(require_role("admin")))],
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
    application, checklist = await attestor_application_service.get_application_by_id(
        db, application_id=application_id
    )
    return _admin_application_response(application, checklist)
