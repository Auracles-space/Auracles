"""Attestation access-package entitlement, presigned access, and audit (§2.5).

Entitlement is derived from live Attestation/Offer status — never stored — so
revocation is automatic. Full content access additionally requires the per-accept
content-use acknowledgment recorded on the attestation row.

Maps to: FR §2.5 (Framework Access Package).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.attestation import matching_service
from app.modules.attestation.models import (
    Attestation,
    AttestationArtifactAccess,
    AttestationOffer,
)
from app.modules.attestation.schemas import (
    AttestationArtifactAccessResponse,
    AttestationPackageArtifact,
    AttestationPackageResponse,
)
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework, FrameworkVersionArtifact
from app.modules.frameworks.models_artifact import Artifact

AccessScope = Literal["preview", "full", "none"]

FULL_ACCESS_STATUSES = frozenset({"accepted", "report_submitted", "disputed"})


async def attestation_access_scope(
    db: AsyncSession,
    *,
    attestation: Attestation,
    user: User,
) -> AccessScope:
    """Compute a user's access scope for an attestation's framework content.

    Entitlement is derived entirely from live status — no grant table exists.
    Full access requires the assigned attestor to be in a review-active status
    *and* to have recorded a content-use acknowledgment. Preview is granted to
    any cohort member holding a live "offered" offer. All other callers get none.

    Args:
        db: Async session for querying offer status.
        attestation: The attestation whose content is being accessed.
        user: The requesting user.

    Returns:
        "full" for the assigned attestor in a review state with an acknowledgment,
        "preview" for a cohort member holding a live offer, otherwise "none".
    """
    # Full: assigned attestor + review-active status + content-use ack
    if (
        attestation.attestor_id == user.id
        and attestation.status in FULL_ACCESS_STATUSES
        and attestation.content_ack_at is not None
    ):
        return "full"

    # Preview: cohort member with a live "offered" offer
    offer_status = await db.scalar(
        select(AttestationOffer.status).where(
            AttestationOffer.attestation_id == attestation.id,
            AttestationOffer.attestor_id == user.id,
        )
    )
    if offer_status == "offered":
        return "preview"

    return "none"


ARTIFACT_ACCESS_URL_TTL_SECONDS = 900


async def _artifact_is_preview_eligible(
    db: AsyncSession, *, framework_id: UUID, artifact_id: UUID
) -> bool:
    """Return True when the artifact is the framework preview.

    Or if it is a preview version artifact.
    """
    preview_artifact_id = await db.scalar(
        select(Framework.preview_artifact_id).where(Framework.id == framework_id)
    )
    if preview_artifact_id == artifact_id:
        return True
    flagged = await db.scalar(
        select(FrameworkVersionArtifact.artifact_id)
        .where(
            FrameworkVersionArtifact.artifact_id == artifact_id,
            FrameworkVersionArtifact.is_preview.is_(True),
        )
        .limit(1)
    )
    return flagged is not None


async def request_artifact_access(
    db: AsyncSession,
    user: User,
    *,
    attestation_id: UUID,
    artifact_id: UUID,
    ip_address: str | None,
) -> AttestationArtifactAccessResponse:
    """Issue an entitlement-checked presigned URL for an Attestation artifact.

    Raises:
        HTTPException(403): Insufficient entitlement, or preview scope on a
            non-preview artifact.
        HTTPException(404): Attestation not visible, or artifact not part of the
            target framework.
    """
    settings = get_settings()
    user_id = user.id
    attestation = await matching_service.get_attestation_for_user(
        db, attestation_id=attestation_id, user=user
    )
    scope = await attestation_access_scope(db, attestation=attestation, user=user)
    if scope == "none":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No access to this Attestation's content.",
        )
    artifact = await db.scalar(
        select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.framework_id == attestation.target_id,
        )
    )
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact not found for this Attestation.",
        )
    if scope == "preview" and not await _artifact_is_preview_eligible(
        db, framework_id=attestation.target_id, artifact_id=artifact_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Preview access does not cover this Artifact.",
        )
    download_url = s3.storage.presigned_get(
        settings.s3_artifacts_bucket,
        artifact.file_key,
        ARTIFACT_ACCESS_URL_TTL_SECONDS,
    )
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        # Log the access event
        access = AttestationArtifactAccess(
            attestation_id=attestation_id,
            artifact_id=artifact_id,
            attestor_id=user_id,
            ip_address=ip_address,
            scope=scope,
        )
        db.add(access)

        await write_audit(
            db=db,
            actor_id=user_id,
            action="attestation_artifact_accessed",
            target_type="attestation",
            target_id=attestation_id,
            metadata={
                "artifact_id": str(artifact_id),
                "scope": scope,
                "ip_address": ip_address,
            },
        )
    logger.bind(
        module="attestation",
        action="request_artifact_access",
        user_id=user_id,
        attestation_id=attestation_id,
        artifact_id=artifact_id,
    ).info("attestation_artifact_accessed")
    return AttestationArtifactAccessResponse(
        artifact_id=artifact_id,
        attestation_id=attestation_id,
        scope=scope,
        download_url=download_url,
        expires_in=ARTIFACT_ACCESS_URL_TTL_SECONDS,
    )


async def get_attestation_package(
    db: AsyncSession,
    user: User,
    *,
    attestation_id: UUID,
) -> AttestationPackageResponse:
    """Assemble the access package scoped to the caller's entitlement.

    Returns framework metadata, the brief, the computed entitlement, and an artifact
    list — the preview subset for preview scope, all artifacts for full, empty for none.
    """
    attestation = await matching_service.get_attestation_for_user(
        db, attestation_id=attestation_id, user=user
    )
    scope = await attestation_access_scope(db, attestation=attestation, user=user)
    framework = await db.get(Framework, attestation.target_id)
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    artifacts: list[AttestationPackageArtifact] = []
    if scope == "full":
        rows = await db.execute(
            select(Artifact).where(Artifact.framework_id == framework.id)
        )
        artifacts = [
            AttestationPackageArtifact(id=a.id, filename=a.name)
            for a in rows.scalars().all()
        ]
    elif scope == "preview":
        preview_ids: set[UUID] = set()
        if framework.preview_artifact_id is not None:
            preview_ids.add(framework.preview_artifact_id)
        flagged = await db.execute(
            select(FrameworkVersionArtifact.artifact_id).where(
                FrameworkVersionArtifact.is_preview.is_(True),
            )
        )
        for (artifact_id,) in flagged.all():
            preview_ids.add(artifact_id)
        if preview_ids:
            rows = await db.execute(
                select(Artifact).where(
                    Artifact.framework_id == framework.id,
                    Artifact.id.in_(preview_ids),
                )
            )
            artifacts = [
                AttestationPackageArtifact(id=a.id, filename=a.name)
                for a in rows.scalars().all()
            ]
    return AttestationPackageResponse(
        attestation_id=attestation.id,
        framework_title=framework.title,
        framework_category=framework.category,
        framework_industry=framework.industry,
        brief=attestation.brief,
        entitlement=scope,
        artifacts=artifacts,
    )
