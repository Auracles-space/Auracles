"""FastAPI router for contributor Framework management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError  # type: ignore[import-untyped]
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    require_kyc_verified,
    require_profile_complete,
    require_role,
)
from app.core.security import decode_access_token
from app.modules.auth.models import User
from app.modules.frameworks import service
from app.modules.frameworks.schemas import (
    ArtifactConfirmRequest,
    ArtifactResponse,
    ArtifactUploadUrlRequest,
    ArtifactUploadUrlResponse,
    FrameworkCreate,
    FrameworkListItem,
    FrameworkResponse,
    FrameworkReviewCreate,
    FrameworkReviewListResponse,
    FrameworkReviewResponse,
    FrameworkReviewUpdate,
    FrameworkUpdate,
    FrameworkVersionCreate,
    PreviewArtifactRequest,
    SimilarityNoticeAcknowledgementRequest,
)

router = APIRouter(prefix="/frameworks", tags=["Frameworks"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
ContributorUser = Annotated[User, Depends(require_role("contributor"))]
OperatorUser = Annotated[User, Depends(require_role("operator"))]
KycVerifiedUser = Annotated[User, Depends(require_kyc_verified)]
ProfileCompleteUser = Annotated[User, Depends(require_profile_complete)]
optional_bearer = HTTPBearer(auto_error=False)


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
        contributor=contributor,
        payload=payload,
    )


@router.get("", response_model=list[FrameworkListItem])
async def list_frameworks(
    contributor: ContributorUser,
    db: DatabaseSession,
) -> list[FrameworkListItem]:
    """List Frameworks owned by the authenticated Contributor."""
    return await service.list_contributor_frameworks(db=db, contributor=contributor)


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
        contributor=contributor,
        framework_id=framework_id,
        payload=payload,
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
        contributor=contributor,
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
        contributor=contributor,
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
        contributor=contributor,
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
        contributor=contributor,
        framework_id=framework_id,
        payload=payload,
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
        contributor=contributor,
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
