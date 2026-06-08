"""FastAPI router for Operator library and licensed downloads."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_kyc_verified, require_role
from app.modules.auth.models import User
from app.modules.library import service
from app.modules.library.schemas import ArtifactDownloadResponse, LibraryResponse

router = APIRouter(tags=["Library"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
OperatorUser = Annotated[User, Depends(require_role("operator"))]
KycVerifiedUser = Annotated[User, Depends(require_kyc_verified)]


@router.get("/library", response_model=LibraryResponse)
async def list_library(
    operator: OperatorUser,
    db: DatabaseSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> LibraryResponse:
    """Return the authenticated Operator's Framework library."""
    return await service.list_operator_library(
        db=db,
        operator=operator,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/frameworks/{framework_id}/artifacts/{artifact_id}/download",
    response_model=ArtifactDownloadResponse,
)
async def download_artifact(
    framework_id: UUID,
    artifact_id: UUID,
    request: Request,
    operator: OperatorUser,
    _: KycVerifiedUser,
    db: DatabaseSession,
) -> ArtifactDownloadResponse:
    """Return a short-lived download URL for a licensed Artifact."""
    return await service.request_artifact_download(
        db=db,
        operator=operator,
        framework_id=framework_id,
        artifact_id=artifact_id,
        ip_address=request.client.host if request.client else None,
    )
