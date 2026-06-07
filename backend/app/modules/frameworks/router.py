"""FastAPI router for contributor Framework management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    require_kyc_verified,
    require_profile_complete,
    require_role,
)
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
    FrameworkUpdate,
    PreviewArtifactRequest,
)

router = APIRouter(prefix="/frameworks", tags=["Frameworks"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
ContributorUser = Annotated[User, Depends(require_role("contributor"))]
KycVerifiedUser = Annotated[User, Depends(require_kyc_verified)]
ProfileCompleteUser = Annotated[User, Depends(require_profile_complete)]


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
