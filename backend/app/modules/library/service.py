"""Service logic for Operator library and licensed downloads."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.auth.models import User
from app.modules.frameworks.models import (
    Framework,
    FrameworkVersion,
    FrameworkVersionArtifact,
    License,
)
from app.modules.frameworks.models_artifact import Artifact, ArtifactDownload
from app.modules.library.schemas import (
    ArtifactDownloadResponse,
    LibraryItem,
    LibraryResponse,
)

ARTIFACT_DOWNLOAD_URL_TTL_SECONDS = 900


def _library_item(framework: Framework, license_row: License) -> LibraryItem:
    """Map a license and Framework row into Operator library response data."""
    return LibraryItem(
        license_id=license_row.id,
        framework_id=framework.id,
        title=framework.title,
        version_at_grant=license_row.version_at_grant,
        current_version=framework.version,
        license_type=license_row.license_type,
        source=license_row.source,
        collection_id=license_row.collection_id,
        status=license_row.status,
        seats_used=license_row.seats_used,
        seats_total=license_row.seats_total,
        price=framework.price,
        currency=framework.currency,
        thumbnail_key=framework.thumbnail_key,
        granted_at=license_row.granted_at,
        expires_at=license_row.expires_at,
    )


async def list_operator_library(
    db: AsyncSession,
    operator: User,
    *,
    page: int,
    page_size: int,
) -> LibraryResponse:
    """Return active Framework licenses held by an Operator."""
    base_query = (
        select(License, Framework)
        .join(Framework, Framework.id == License.framework_id)
        .where(License.operator_id == operator.id)
        .order_by(License.granted_at.desc())
    )
    total = int(
        await db.scalar(
            select(func.count()).select_from(base_query.subquery())
        )
        or 0
    )
    rows = await db.execute(base_query.offset((page - 1) * page_size).limit(page_size))
    return LibraryResponse(
        items=[
            _library_item(framework, license_row)
            for license_row, framework in rows.all()
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


async def _load_active_license(
    db: AsyncSession,
    operator: User,
    framework_id: UUID,
) -> License:
    """Load the Operator's active license for a Framework or reject access."""
    license_row = await db.scalar(
        select(License).where(
            License.framework_id == framework_id,
            License.operator_id == operator.id,
            License.status == "active",
        )
    )
    if license_row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active license required.",
        )
    return license_row


async def _load_active_license_by_operator_id(
    db: AsyncSession,
    operator_id: UUID,
    framework_id: UUID,
) -> License:
    """Load an active license by Operator id or reject access."""
    license_row = await db.scalar(
        select(License).where(
            License.framework_id == framework_id,
            License.operator_id == operator_id,
            License.status == "active",
        )
    )
    if license_row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active license required.",
        )
    return license_row


async def _artifact_is_covered_by_license_version(
    db: AsyncSession,
    license_row: License,
    artifact_id: UUID,
) -> bool:
    """Return whether an Artifact belongs to the licensed version snapshot."""
    snapshot = await db.scalar(
        select(FrameworkVersion).where(
            FrameworkVersion.framework_id == license_row.framework_id,
            FrameworkVersion.version == license_row.version_at_grant,
        )
    )
    if snapshot is None:
        return False
    snapshot_artifact = await db.get(
        FrameworkVersionArtifact,
        (snapshot.id, artifact_id),
    )
    return snapshot_artifact is not None


async def request_artifact_download(
    db: AsyncSession,
    operator: User,
    *,
    framework_id: UUID,
    artifact_id: UUID,
    ip_address: str | None,
) -> ArtifactDownloadResponse:
    """Issue a presigned GET URL after license and version checks pass."""
    settings = get_settings()
    operator_id = operator.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        license_row = await _load_active_license_by_operator_id(
            db,
            operator_id,
            framework_id,
        )
        artifact = await db.scalar(
            select(Artifact).where(
                Artifact.id == artifact_id,
                Artifact.framework_id == framework_id,
            )
        )
        if artifact is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Artifact not found.",
            )
        if not await _artifact_is_covered_by_license_version(
            db,
            license_row,
            artifact.id,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="License does not cover this Artifact version.",
            )

        download_url = s3.storage.presigned_get(
            settings.s3_artifacts_bucket,
            artifact.file_key,
            ARTIFACT_DOWNLOAD_URL_TTL_SECONDS,
        )
        download = ArtifactDownload(
            license_id=license_row.id,
            artifact_id=artifact.id,
            user_id=operator_id,
            ip_address=ip_address,
        )
        db.add(download)
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="artifact_downloaded",
            target_type="artifact",
            target_id=artifact.id,
            metadata={
                "framework_id": str(framework_id),
                "license_id": str(license_row.id),
            },
        )
    logger.bind(
        module="library",
        action="request_artifact_download",
        user_id=operator_id,
        framework_id=framework_id,
        artifact_id=artifact.id,
    ).info("artifact_downloaded")
    return ArtifactDownloadResponse(
        artifact_id=artifact.id,
        framework_id=framework_id,
        license_id=license_row.id,
        download_url=download_url,
        expires_in=ARTIFACT_DOWNLOAD_URL_TTL_SECONDS,
    )
