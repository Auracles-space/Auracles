"""FastAPI router for contributor Framework management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError  # type: ignore[import-untyped]
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    get_current_user,
    require_kyc_verified,
    require_profile_complete,
    require_role,
)
from app.core.security import decode_access_token
from app.modules.attestation import badge_service
from app.modules.auth.models import User, UserRole
from app.modules.explore.schemas import AttestationBadgeDetail
from app.modules.frameworks import service
from app.modules.frameworks.models import Framework
from app.modules.frameworks.ownership import FrameworkOwner
from app.modules.frameworks.schemas import (
    ArtifactConfirmRequest,
    ArtifactFromConnectorRequest,
    ArtifactResponse,
    ArtifactUploadUrlRequest,
    ArtifactUploadUrlResponse,
    BindSourceRequest,
    FrameworkCreate,
    FrameworkListItem,
    FrameworkMetadataUpdate,
    FrameworkPricingUpdate,
    FrameworkResponse,
    FrameworkReviewCreate,
    FrameworkReviewListResponse,
    FrameworkReviewResponse,
    FrameworkReviewUpdate,
    FrameworkUpdate,
    FrameworkVersionCreate,
    PreviewArtifactRequest,
    SimilarityNoticeAcknowledgementRequest,
    SourcePreviewResponse,
)
from app.modules.organizations.dependencies import (
    OrgContext,
    require_org_capability,
    require_org_capability_grant,
    require_org_role,
)

router = APIRouter(prefix="/frameworks", tags=["Frameworks"])
org_router = APIRouter(prefix="/orgs/{org_id}/frameworks", tags=["Frameworks"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
ContributorUser = Annotated[User, Depends(require_role("contributor"))]
OperatorUser = Annotated[User, Depends(require_role("operator"))]
CurrentUser = Annotated[User, Depends(get_current_user)]
KycVerifiedUser = Annotated[User, Depends(require_kyc_verified)]
ProfileCompleteUser = Annotated[User, Depends(require_profile_complete)]
OrgMemberContext = Annotated[OrgContext, Depends(require_org_role("member"))]
OrgAdminContext = Annotated[OrgContext, Depends(require_org_role("admin"))]
OrgContributorContext = Annotated[
    OrgContext, Depends(require_org_capability_grant("contributor"))
]
optional_bearer = HTTPBearer(auto_error=False)


def _self_owner(user: User) -> FrameworkOwner:
    """Build a self-owned Framework context for an individual Contributor."""
    return FrameworkOwner(
        actor_id=user.id,
        user_id=user.id,
        org_id=None,
        authoring_member_id=None,
        can_manage_live_state=True,
    )


def _org_owner(context: OrgContext) -> FrameworkOwner:
    """Build an organization-owned Framework context from an org membership."""
    return FrameworkOwner(
        actor_id=context.user.id,
        user_id=None,
        org_id=context.org.id,
        authoring_member_id=context.member.id,
        can_manage_live_state=context.member.role in {"owner", "admin"},
    )


async def optional_review_viewer(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(optional_bearer),
    ],
) -> tuple[UUID | None, set[str]]:
    """Return optional bearer identity for review visibility checks."""
    if credentials is None:
        return None, set()
    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError:
        return None, set()
    return payload.sub, set(payload.roles)


@router.post(
    "",
    response_model=FrameworkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_framework(
    payload: FrameworkCreate,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Create a draft Framework for the authenticated Contributor."""
    return await service.create_framework(
        db=db,
        owner=_self_owner(contributor),
        payload=payload,
    )


@org_router.post(
    "",
    response_model=FrameworkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create organization Framework",
    description=(
        "Create a draft Framework under the organization contributor identity "
        "as an organization member while the contributor capability is active."
    ),
)
async def create_org_framework(
    org_id: UUID,
    payload: FrameworkCreate,
    context: OrgContributorContext,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Create a draft Framework owned by the organization."""
    del org_id
    return await service.create_framework(
        db=db,
        owner=_org_owner(context),
        payload=payload,
    )


@router.get("", response_model=list[FrameworkListItem])
async def list_frameworks(
    contributor: ContributorUser,
    db: DatabaseSession,
) -> list[FrameworkListItem]:
    """List Frameworks owned by the authenticated Contributor."""
    return await service.list_contributor_frameworks(db=db, contributor=contributor)


@org_router.get(
    "",
    response_model=list[FrameworkListItem],
    summary="List organization Frameworks",
    description=(
        "List Frameworks owned by the organization contributor identity for "
        "organization members while the contributor capability is active."
    ),
)
async def list_org_frameworks(
    org_id: UUID,
    context: OrgContributorContext,
    db: DatabaseSession,
) -> list[FrameworkListItem]:
    """List Frameworks owned by one organization."""
    del org_id
    return await service.list_frameworks_for_owner(
        db=db,
        owner=_org_owner(context),
    )


@router.post(
    "/{framework_id}/reviews",
    response_model=FrameworkReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_framework_review(
    framework_id: UUID,
    payload: FrameworkReviewCreate,
    operator: OperatorUser,
    db: DatabaseSession,
) -> FrameworkReviewResponse:
    """Create the authenticated Operator's review for a licensed Framework."""
    return await service.create_framework_review(
        db=db,
        operator=operator,
        framework_id=framework_id,
        payload=payload,
    )


@router.patch(
    "/{framework_id}/reviews/me",
    response_model=FrameworkReviewResponse,
)
async def update_my_framework_review(
    framework_id: UUID,
    payload: FrameworkReviewUpdate,
    operator: OperatorUser,
    db: DatabaseSession,
) -> FrameworkReviewResponse:
    """Edit the authenticated Operator's own Framework review."""
    return await service.update_my_framework_review(
        db=db,
        operator=operator,
        framework_id=framework_id,
        payload=payload,
    )


@router.get(
    "/{framework_id}/reviews",
    response_model=FrameworkReviewListResponse,
)
async def list_framework_reviews(
    framework_id: UUID,
    viewer: Annotated[tuple[UUID | None, set[str]], Depends(optional_review_viewer)],
    db: DatabaseSession,
) -> FrameworkReviewListResponse:
    """List reviews and aggregate score for one Framework."""
    viewer_id, viewer_roles = viewer
    return await service.list_framework_reviews(
        db=db,
        framework_id=framework_id,
        viewer_id=viewer_id,
        viewer_roles=viewer_roles,
    )


@router.get("/{framework_id}", response_model=FrameworkResponse)
async def get_framework(
    framework_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Return one Framework owned by the authenticated Contributor."""
    return await service.get_framework_for_contributor(
        db=db,
        contributor=contributor,
        framework_id=framework_id,
    )


@org_router.get(
    "/{framework_id}",
    response_model=FrameworkResponse,
    summary="Get organization Framework",
    description=(
        "Return one organization-owned Framework for an organization member "
        "while the contributor capability is active."
    ),
)
async def get_org_framework(
    org_id: UUID,
    framework_id: UUID,
    context: OrgContributorContext,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Return one Framework owned by the organization."""
    del org_id
    return await service.get_framework_for_owner(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
    )


@router.get(
    "/{framework_id}/attestation-badges",
    response_model=list[AttestationBadgeDetail],
    summary="List all attestation badges for a framework (owner or admin)",
)
async def list_framework_attestation_badges(
    framework_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> list[AttestationBadgeDetail]:
    """Return the full attestation provenance for a framework.

    Only the framework owner or an admin may read this surface. It includes
    rejected determinations hidden from the public framework page.
    """
    framework = await db.scalar(select(Framework).where(Framework.id == framework_id))
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    is_admin = (
        await db.scalar(
            select(UserRole.id).where(
                UserRole.user_id == current_user.id,
                UserRole.role == "admin",
                UserRole.approved_at.is_not(None),
            )
        )
        is not None
    )
    if framework.contributor_id != current_user.id and not is_admin:
        logger.bind(
            module="attestation",
            action="framework_provenance_denied",
            user_id=current_user.id,
            framework_id=framework_id,
        ).warning("access_denied")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not permitted.",
        )
    return await badge_service.list_framework_provenance(db, framework=framework)


@router.patch("/{framework_id}", response_model=FrameworkResponse)
async def update_framework(
    framework_id: UUID,
    payload: FrameworkUpdate,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Update an owned draft Framework."""
    return await service.update_framework(
        db=db,
        owner=_self_owner(contributor),
        framework_id=framework_id,
        payload=payload,
    )


@org_router.patch(
    "/{framework_id}",
    response_model=FrameworkResponse,
    summary="Update organization Framework metadata",
    description=(
        "Update editable metadata for an organization-owned Framework as an "
        "organization member while the contributor capability is active."
    ),
)
async def update_org_framework(
    org_id: UUID,
    framework_id: UUID,
    payload: FrameworkMetadataUpdate,
    context: OrgContributorContext,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Update organization-owned Framework metadata."""
    del org_id
    return await service.update_framework(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
        payload=FrameworkUpdate(**payload.model_dump(exclude_unset=True)),
    )


@org_router.patch(
    "/{framework_id}/pricing",
    response_model=FrameworkResponse,
    summary="Update organization Framework pricing",
    description=(
        "Update pricing for an organization-owned Framework as an organization "
        "owner or admin while the contributor capability is active."
    ),
)
async def update_org_framework_pricing(
    org_id: UUID,
    framework_id: UUID,
    payload: FrameworkPricingUpdate,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("contributor"))],
    db: DatabaseSession,
) -> FrameworkResponse:
    """Update organization-owned Framework pricing."""
    del org_id
    return await service.update_framework(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
        payload=FrameworkUpdate(pricing=payload.pricing),
    )


@router.delete("/{framework_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_framework(
    framework_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> Response:
    """Delete an owned draft Framework."""
    await service.delete_draft(
        db=db,
        contributor=contributor,
        framework_id=framework_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{framework_id}/unpublish", response_model=FrameworkResponse)
async def unpublish_framework(
    framework_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Unpublish an owned Framework so new catalog purchases stop."""
    return await service.unpublish_framework(
        db=db,
        owner=_self_owner(contributor),
        framework_id=framework_id,
    )


@org_router.post(
    "/{framework_id}/unpublish",
    response_model=FrameworkResponse,
    summary="Unpublish organization Framework",
    description=(
        "Unpublish an organization-owned Framework so new catalog purchases "
        "stop. Restricted to organization owners and admins while the "
        "contributor capability is active."
    ),
)
async def unpublish_org_framework(
    org_id: UUID,
    framework_id: UUID,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("contributor"))],
    db: DatabaseSession,
) -> FrameworkResponse:
    """Unpublish one organization-owned Framework."""
    del org_id
    return await service.unpublish_framework(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
    )


@org_router.post(
    "/{framework_id}/relist",
    response_model=FrameworkResponse,
    summary="Relist organization Framework",
    description=(
        "Return a delisted organization-owned Framework to the public catalog. "
        "Requires organization owner/admin access and an active contributor "
        "capability."
    ),
)
async def relist_org_framework(
    org_id: UUID,
    framework_id: UUID,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("contributor"))],
    db: DatabaseSession,
) -> FrameworkResponse:
    """Relist one delisted organization-owned Framework."""
    del org_id
    return await service.relist_framework_for_owner(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
    )


@router.post("/{framework_id}/relist", response_model=FrameworkResponse)
async def relist_framework(
    framework_id: UUID,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Relist an owned, delisted Framework back into the public catalog."""
    return await service.relist_framework(
        db=db,
        contributor=contributor,
        framework_id=framework_id,
    )


@router.post("/{framework_id}/versions", response_model=FrameworkResponse)
async def create_new_version(
    framework_id: UUID,
    payload: FrameworkVersionCreate,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Start a new editable draft version of an owned Framework."""
    return await service.create_new_version(
        db=db,
        owner=_self_owner(contributor),
        framework_id=framework_id,
        payload=payload,
    )


@org_router.post(
    "/{framework_id}/version",
    response_model=FrameworkResponse,
    summary="Start organization Framework version",
    description=(
        "Start a new editable draft version of an organization-owned Framework. "
        "Restricted to organization owners and admins while the contributor "
        "capability is active."
    ),
)
async def create_new_org_version(
    org_id: UUID,
    framework_id: UUID,
    payload: FrameworkVersionCreate,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("contributor"))],
    db: DatabaseSession,
) -> FrameworkResponse:
    """Start a new draft version for an organization-owned Framework."""
    del org_id
    return await service.create_new_version(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
        payload=payload,
    )


@router.post("/{framework_id}/submit", response_model=FrameworkResponse)
async def submit_framework(
    framework_id: UUID,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Submit an owned Framework to the processing gate."""
    return await service.submit_framework(
        db=db,
        owner=_self_owner(contributor),
        framework_id=framework_id,
    )


@org_router.post(
    "/{framework_id}/submit",
    response_model=FrameworkResponse,
    summary="Submit organization Framework",
    description=(
        "Submit an organization-owned Framework to the processing gate as an "
        "organization member while the contributor capability is active."
    ),
)
async def submit_org_framework(
    org_id: UUID,
    framework_id: UUID,
    context: OrgContributorContext,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Submit one organization-owned Framework."""
    del org_id
    return await service.submit_framework(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
    )


@router.post("/{framework_id}/acknowledge-soft-fail", response_model=FrameworkResponse)
async def acknowledge_soft_fail(
    framework_id: UUID,
    request: Request,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Acknowledge an external-rarity soft fail without publishing."""
    return await service.acknowledge_soft_fail(
        db=db,
        contributor=contributor,
        framework_id=framework_id,
        ip_address=request.client.host if request.client else None,
    )


@router.post(
    "/{framework_id}/similarity-notice/acknowledge",
    response_model=FrameworkResponse,
)
async def acknowledge_similarity_notice(
    framework_id: UUID,
    payload: SimilarityNoticeAcknowledgementRequest,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Record Contributor context for a non-blocking similarity notice."""
    return await service.acknowledge_similarity_notice(
        db=db,
        contributor=contributor,
        framework_id=framework_id,
        payload=payload,
    )


@router.post("/{framework_id}/publish", response_model=FrameworkResponse)
async def publish_framework(
    framework_id: UUID,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Publish an owned Framework after pipeline checks pass."""
    return await service.publish_framework(
        db=db,
        owner=_self_owner(contributor),
        framework_id=framework_id,
    )


@org_router.post(
    "/{framework_id}/publish",
    response_model=FrameworkResponse,
    summary="Publish organization Framework",
    description=(
        "Publish an organization-owned Framework after pipeline checks pass. "
        "Restricted to organization owners and admins while the contributor "
        "capability is active."
    ),
)
async def publish_org_framework(
    org_id: UUID,
    framework_id: UUID,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("contributor"))],
    db: DatabaseSession,
) -> FrameworkResponse:
    """Publish one organization-owned Framework."""
    del org_id
    return await service.publish_framework(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
    )


@router.post(
    "/{framework_id}/artifacts/upload-url",
    response_model=ArtifactUploadUrlResponse,
)
async def request_artifact_upload_url(
    framework_id: UUID,
    payload: ArtifactUploadUrlRequest,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> ArtifactUploadUrlResponse:
    """Create a private S3 upload target for a draft Framework Artifact."""
    return await service.request_artifact_upload_url(
        db=db,
        owner=_self_owner(contributor),
        framework_id=framework_id,
        payload=payload,
    )


@org_router.post(
    "/{framework_id}/artifacts/upload-url",
    response_model=ArtifactUploadUrlResponse,
    summary="Create organization artifact upload URL",
    description=(
        "Create a private S3 upload target for an organization-owned Framework "
        "artifact while the contributor capability is active."
    ),
)
async def request_org_artifact_upload_url(
    org_id: UUID,
    framework_id: UUID,
    payload: ArtifactUploadUrlRequest,
    context: OrgContributorContext,
    db: DatabaseSession,
) -> ArtifactUploadUrlResponse:
    """Create a private upload target for an organization Framework artifact."""
    del org_id
    return await service.request_artifact_upload_url(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
        payload=payload,
    )


@org_router.get(
    "/{framework_id}/artifacts",
    response_model=list[ArtifactResponse],
    summary="List organization Framework artifacts",
    description=(
        "List current Artifacts attached to an organization-owned Framework for "
        "an organization member holding the contributor capability grant."
    ),
)
async def list_org_framework_artifacts(
    org_id: UUID,
    framework_id: UUID,
    context: OrgContributorContext,
    db: DatabaseSession,
) -> list[ArtifactResponse]:
    """List current Artifacts for one organization-owned Framework."""
    del org_id
    return await service.list_artifacts_for_owner(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
    )


@org_router.delete(
    "/{framework_id}/artifacts/{artifact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete organization Framework artifact",
    description=(
        "Delete an Artifact from an organization-owned draft Framework for an "
        "organization member holding the contributor capability grant."
    ),
)
async def delete_org_framework_artifact(
    org_id: UUID,
    framework_id: UUID,
    artifact_id: UUID,
    context: OrgContributorContext,
    db: DatabaseSession,
) -> Response:
    """Delete an Artifact from one organization-owned Framework."""
    del org_id
    await service.delete_artifact_for_owner(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
        artifact_id=artifact_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@org_router.patch(
    "/{framework_id}/preview-artifact",
    response_model=FrameworkResponse,
    summary="Set organization Framework preview artifact",
    description=(
        "Designate one Artifact as the public preview on an organization-owned "
        "draft Framework for a member holding the contributor capability grant."
    ),
)
async def set_org_framework_preview_artifact(
    org_id: UUID,
    framework_id: UUID,
    payload: PreviewArtifactRequest,
    context: OrgContributorContext,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Set the preview Artifact on one organization-owned Framework."""
    del org_id
    return await service.set_preview_artifact_for_owner(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
        payload=payload,
    )


@org_router.post(
    "/{framework_id}/artifacts/{artifact_id}/resolve-pii-review",
    response_model=ArtifactResponse,
    summary="Re-run PII review on an organization Framework artifact",
    description=(
        "Reset a replaced PII-flagged Artifact and re-run processing on an "
        "organization-owned Framework for a member holding the contributor grant."
    ),
)
async def resolve_org_framework_pii_review(
    org_id: UUID,
    framework_id: UUID,
    artifact_id: UUID,
    context: OrgContributorContext,
    db: DatabaseSession,
) -> ArtifactResponse:
    """Re-run PII review for one organization-owned Framework Artifact."""
    del org_id
    return await service.resolve_pii_review_for_owner(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
        artifact_id=artifact_id,
    )


@org_router.post(
    "/{framework_id}/artifacts/{artifact_id}/accept-redaction",
    response_model=ArtifactResponse,
    summary="Accept a redacted copy on an organization Framework artifact",
    description=(
        "Accept a generated redacted Artifact copy and re-run processing on an "
        "organization-owned Framework for a member holding the contributor grant."
    ),
)
async def accept_org_framework_redaction(
    org_id: UUID,
    framework_id: UUID,
    artifact_id: UUID,
    context: OrgContributorContext,
    db: DatabaseSession,
) -> ArtifactResponse:
    """Accept a redacted copy for one organization-owned Framework Artifact."""
    del org_id
    return await service.accept_redaction_for_owner(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
        artifact_id=artifact_id,
    )


@router.get("/{framework_id}/artifacts", response_model=list[ArtifactResponse])
async def list_artifacts(
    framework_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> list[ArtifactResponse]:
    """List Artifacts attached to an owned Framework."""
    return await service.list_artifacts(
        db=db,
        contributor=contributor,
        framework_id=framework_id,
    )


@router.post(
    "/{framework_id}/artifacts/from-connector",
    response_model=ArtifactResponse,
    summary="Import an Artifact from a connected source",
    description=(
        "Copy a file from the contributor's connected provider into "
        "private storage as a new draft Artifact and run the standard "
        "processing pipeline on it."
    ),
)
async def import_artifact_from_connector(
    framework_id: UUID,
    payload: ArtifactFromConnectorRequest,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> ArtifactResponse:
    """Import a connected-source file as a new draft Artifact."""
    return await service.import_artifact_from_connector(
        db=db,
        contributor=contributor,
        framework_id=framework_id,
        payload=payload,
    )


@router.get(
    "/{framework_id}/artifacts/{artifact_id}/source-preview",
    response_model=SourcePreviewResponse,
    summary="Draft live-mirror preview for a connector-bound artifact",
    description=(
        "Owner-only, pre-publish-only. Returns a presigned thumbnail of the "
        "current source file and whether the source changed since import. "
        "Never exposed on public, catalog, or buyer surfaces."
    ),
)
async def get_artifact_source_preview(
    framework_id: UUID,
    artifact_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> SourcePreviewResponse:
    """Return the owner-only draft source preview for a connector-bound artifact."""
    return await service.get_source_preview(
        db=db,
        contributor=contributor,
        framework_id=framework_id,
        artifact_id=artifact_id,
    )


@router.post(
    "/{framework_id}/artifacts/{artifact_id}/resync",
    response_model=ArtifactResponse,
    summary="Re-sync a connector-bound artifact from its source",
    description=(
        "Owner-only, pre-publish-only. Pulls the latest bytes of the artifact's "
        "bound source into a new artifact version and re-runs the pipeline. "
        "Returns a new artifact id on change; 409 already_up_to_date when the "
        "source is unchanged. A 404 on the old id afterward means it was "
        "superseded — refetch the artifact list."
    ),
)
async def resync_artifact(
    framework_id: UUID,
    artifact_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> ArtifactResponse:
    """Pull the latest source bytes into a new artifact version."""
    return await service.resync_artifact(db, contributor, framework_id, artifact_id)


@router.post(
    "/{framework_id}/artifacts/{artifact_id}/bind-source",
    response_model=ArtifactResponse,
    summary="Attach or repoint an artifact's connector source",
    description=(
        "Owner-only, pre-publish-only. Binds the artifact to the given "
        "connector file and pulls its bytes into a new artifact version. "
        "Works on an unbound (upload) artifact (attach) or an already-bound "
        "one (repoint). Returns a new artifact id."
    ),
)
async def bind_artifact_source(
    framework_id: UUID,
    artifact_id: UUID,
    payload: BindSourceRequest,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> ArtifactResponse:
    """Bind (attach/repoint) an artifact to a connector source and pull bytes."""
    return await service.bind_artifact_source(
        db, contributor, framework_id, artifact_id, payload
    )


@router.delete(
    "/{framework_id}/artifacts/{artifact_id}/source",
    response_model=ArtifactResponse,
    summary="Detach an artifact's connector source",
    description=(
        "Owner-only, pre-publish-only. Drops the connector binding and keeps "
        "the owned bytes as a plain upload. Metadata-only; the artifact id is "
        "unchanged."
    ),
)
async def detach_artifact_source(
    framework_id: UUID,
    artifact_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> ArtifactResponse:
    """Detach the artifact's connector source, keeping its bytes."""
    return await service.detach_artifact_source(
        db, contributor, framework_id, artifact_id
    )


@router.post("/{framework_id}/artifacts/confirm", response_model=ArtifactResponse)
async def confirm_artifact_upload(
    framework_id: UUID,
    payload: ArtifactConfirmRequest,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> ArtifactResponse:
    """Confirm an uploaded Artifact and dispatch virus scanning."""
    return await service.confirm_artifact_upload(
        db=db,
        owner=_self_owner(contributor),
        framework_id=framework_id,
        payload=payload,
    )


@org_router.post(
    "/{framework_id}/artifacts/confirm",
    response_model=ArtifactResponse,
    summary="Confirm organization artifact upload",
    description=(
        "Confirm an uploaded artifact for an organization-owned Framework and "
        "dispatch scanning while the contributor capability is active."
    ),
)
async def confirm_org_artifact_upload(
    org_id: UUID,
    framework_id: UUID,
    payload: ArtifactConfirmRequest,
    context: OrgContributorContext,
    db: DatabaseSession,
) -> ArtifactResponse:
    """Confirm an uploaded organization Framework artifact."""
    del org_id
    return await service.confirm_artifact_upload(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
        payload=payload,
    )


@router.patch("/{framework_id}/preview-artifact", response_model=FrameworkResponse)
async def set_preview_artifact(
    framework_id: UUID,
    payload: PreviewArtifactRequest,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> FrameworkResponse:
    """Designate one Artifact as the Framework preview Artifact."""
    return await service.set_preview_artifact(
        db=db,
        contributor=contributor,
        framework_id=framework_id,
        payload=payload,
    )


@router.delete(
    "/{framework_id}/artifacts/{artifact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_artifact(
    framework_id: UUID,
    artifact_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> Response:
    """Delete an Artifact from an owned draft Framework."""
    await service.delete_artifact(
        db=db,
        contributor=contributor,
        framework_id=framework_id,
        artifact_id=artifact_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{framework_id}/artifacts/{artifact_id}/resolve-pii-review",
    response_model=ArtifactResponse,
)
async def resolve_pii_review(
    framework_id: UUID,
    artifact_id: UUID,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> ArtifactResponse:
    """Re-run processing after a Contributor replaces a PII-flagged Artifact."""
    return await service.resolve_pii_review(
        db=db,
        contributor=contributor,
        framework_id=framework_id,
        artifact_id=artifact_id,
    )


@router.post(
    "/{framework_id}/artifacts/{artifact_id}/accept-redaction",
    response_model=ArtifactResponse,
)
async def accept_redaction(
    framework_id: UUID,
    artifact_id: UUID,
    contributor: ContributorUser,
    _: KycVerifiedUser,
    __: ProfileCompleteUser,
    db: DatabaseSession,
) -> ArtifactResponse:
    """Accept a generated redacted Artifact copy and re-run processing."""
    return await service.accept_redaction(
        db=db,
        contributor=contributor,
        framework_id=framework_id,
        artifact_id=artifact_id,
    )
