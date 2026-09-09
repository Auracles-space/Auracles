"""Org shared-library service helpers.

Provides the entitlement checks and org-library flows that sit in front of
presigned Artifact downloads for org-owned Licenses.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.frameworks.models import Framework, License, LicenseGrant
from app.modules.frameworks.models_artifact import Artifact, ArtifactDownload
from app.modules.library.schemas import ArtifactDownloadResponse, LibraryItem
from app.modules.organizations.models import OrgMember, OrgTeam, OrgTeamMember


async def member_has_license_access(
    db: AsyncSession,
    *,
    license_id: UUID,
    member_id: UUID,
) -> bool:
    """Return whether one org member has a direct or team grant to one License."""
    grant_id = await db.scalar(
        select(LicenseGrant.id)
        .where(
            LicenseGrant.license_id == license_id,
            or_(
                LicenseGrant.member_id == member_id,
                LicenseGrant.team_id.in_(
                    select(OrgTeamMember.team_id).where(
                        OrgTeamMember.member_id == member_id
                    )
                ),
            ),
        )
        .limit(1)
    )
    return grant_id is not None


async def _load_org_license(
    db: AsyncSession,
    *,
    org_id: UUID,
    license_id: UUID,
) -> License:
    """Load one org-owned License inside the org namespace or raise 404."""
    license_row = await db.scalar(
        select(License).where(
            License.id == license_id,
            License.licensee_org_id == org_id,
        )
    )
    if license_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="License not found.",
        )
    return license_row


async def _load_org_member(
    db: AsyncSession,
    *,
    org_id: UUID,
    member_id: UUID,
) -> OrgMember:
    """Load one org member inside the org namespace or raise 404."""
    member = await db.scalar(
        select(OrgMember).where(
            OrgMember.id == member_id,
            OrgMember.org_id == org_id,
        )
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization member not found.",
        )
    return member


async def add_license_grant(
    db: AsyncSession,
    *,
    org_id: UUID,
    license_id: UUID,
    actor_member_id: UUID,
    team_id: UUID | None = None,
    member_id: UUID | None = None,
) -> LicenseGrant:
    """Allocate one org License to exactly one team or member."""
    if (team_id is None) == (member_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Exactly one grant target is required.",
        )

    if db.in_transaction():
        await db.rollback()

    try:
        async with db.begin():
            await _load_org_license(db, org_id=org_id, license_id=license_id)
            actor_member = await _load_org_member(
                db,
                org_id=org_id,
                member_id=actor_member_id,
            )
            if member_id is not None:
                member = await db.get(OrgMember, member_id)
                if member is None or member.org_id != org_id:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail="Grant target must belong to the organization.",
                    )
            if team_id is not None:
                team = await db.get(OrgTeam, team_id)
                if team is None or team.org_id != org_id:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail="Grant target must belong to the organization.",
                    )

            grant = LicenseGrant(
                license_id=license_id,
                team_id=team_id,
                member_id=member_id,
                granted_by=actor_member_id,
            )
            db.add(grant)
            await db.flush()
            await write_audit(
                db=db,
                actor_id=actor_member.user_id,
                action="license_grant_added",
                target_type="license",
                target_id=license_id,
                metadata={
                    "org_id": str(org_id),
                    "grant_id": str(grant.id),
                },
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="License grant already exists.",
        ) from exc

    await db.refresh(grant)
    return grant


async def revoke_license_grant(
    db: AsyncSession,
    *,
    org_id: UUID,
    license_id: UUID,
    grant_id: UUID,
) -> None:
    """Delete one org License grant inside the org namespace."""
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        await _load_org_license(db, org_id=org_id, license_id=license_id)
        grant = await db.scalar(
            select(LicenseGrant).where(
                LicenseGrant.id == grant_id,
                LicenseGrant.license_id == license_id,
            )
        )
        if grant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="License grant not found.",
            )
        await db.delete(grant)
        await write_audit(
            db=db,
            actor_id=None,
            action="license_grant_revoked",
            target_type="license",
            target_id=license_id,
            metadata={"org_id": str(org_id)},
        )


async def list_license_grants(
    db: AsyncSession,
    *,
    org_id: UUID,
    license_id: UUID,
) -> list[LicenseGrant]:
    """Return all grant rows for one org-owned License."""
    await _load_org_license(db, org_id=org_id, license_id=license_id)
    return list(
        (
            await db.scalars(
                select(LicenseGrant)
                .where(LicenseGrant.license_id == license_id)
                .order_by(LicenseGrant.created_at.asc())
            )
        ).all()
    )


async def list_org_library(
    db: AsyncSession,
    *,
    org_id: UUID,
    member: OrgMember,
) -> list[tuple[LibraryItem, int]]:
    """Return org-library items visible to one member plus grant counts."""
    from app.modules.library.service import _library_item

    rows = (
        await db.execute(
            select(License, Framework)
            .join(Framework, Framework.id == License.framework_id)
            .where(
                License.licensee_org_id == org_id,
                License.status == "active",
            )
            .order_by(License.granted_at.desc())
        )
    ).all()

    visible_rows: list[tuple[License, Framework]] = []
    if member.role in {"admin", "owner"}:
        visible_rows = [
            (license_row, framework) for license_row, framework in rows
        ]
    else:
        # Resolve the member's accessible Licenses in ONE grant query rather
        # than a per-row member_has_license_access call (N+1). A License is
        # visible if the member holds a direct grant or a grant to one of their
        # teams.
        all_license_ids = [license_row.id for license_row, _framework in rows]
        accessible_ids: set[UUID] = set()
        if all_license_ids:
            accessible_ids = set(
                (
                    await db.execute(
                        select(LicenseGrant.license_id)
                        .where(
                            LicenseGrant.license_id.in_(all_license_ids),
                            or_(
                                LicenseGrant.member_id == member.id,
                                LicenseGrant.team_id.in_(
                                    select(OrgTeamMember.team_id).where(
                                        OrgTeamMember.member_id == member.id
                                    )
                                ),
                            ),
                        )
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )
        visible_rows = [
            (license_row, framework)
            for license_row, framework in rows
            if license_row.id in accessible_ids
        ]

    grant_counts: dict[UUID, int] = {}
    license_ids = [license_row.id for license_row, _framework in visible_rows]
    if license_ids:
        counts = await db.execute(
            select(
                LicenseGrant.license_id,
                func.count(LicenseGrant.id),
            )
            .where(LicenseGrant.license_id.in_(license_ids))
            .group_by(LicenseGrant.license_id)
        )
        grant_counts = {
            license_id: int(count)
            for license_id, count in counts.all()
        }

    return [
        (_library_item(framework, license_row), grant_counts.get(license_row.id, 0))
        for license_row, framework in visible_rows
    ]


async def request_org_artifact_download(
    db: AsyncSession,
    *,
    org_id: UUID,
    license_id: UUID,
    artifact_id: UUID,
    member: OrgMember,
    ip_address: str | None,
) -> ArtifactDownloadResponse:
    """Issue an org-library Artifact download only after entitlement checks pass."""
    from app.modules.library.service import (
        ARTIFACT_DOWNLOAD_URL_TTL_SECONDS,
        _artifact_is_covered_by_license_version,
    )

    settings = get_settings()
    member_id = member.id
    member_user_id = member.user_id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        license_row = await _load_org_license(db, org_id=org_id, license_id=license_id)
        if license_row.status != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Active license required.",
            )
        if not await member_has_license_access(
            db,
            license_id=license_id,
            member_id=member_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="License grant required.",
            )

        artifact = await db.scalar(
            select(Artifact).where(
                Artifact.id == artifact_id,
                Artifact.framework_id == license_row.framework_id,
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
            download_name=artifact.name,
        )
        db.add(
            ArtifactDownload(
                license_id=license_row.id,
                artifact_id=artifact.id,
                user_id=member_user_id,
                ip_address=ip_address,
            )
        )
        await write_audit(
            db=db,
            actor_id=member_user_id,
            action="artifact_downloaded",
            target_type="artifact",
            target_id=artifact.id,
            metadata={
                "framework_id": str(license_row.framework_id),
                "license_id": str(license_row.id),
            },
            ip=ip_address,
        )

    logger.bind(
        module="organizations",
        action="request_org_artifact_download",
        user_id=str(member_user_id),
        org_id=str(org_id),
        artifact_id=str(artifact_id),
    ).info("artifact_downloaded")
    return ArtifactDownloadResponse(
        artifact_id=artifact.id,
        framework_id=license_row.framework_id,
        license_id=license_row.id,
        download_url=download_url,
        expires_in=ARTIFACT_DOWNLOAD_URL_TTL_SECONDS,
    )
