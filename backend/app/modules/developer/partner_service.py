"""Partner API marketplace read service.

Partner reads intentionally reuse public Explore visibility rules and response
mapping where possible. Partner endpoints may expose only public marketplace
metadata and explicitly gated preview/report metadata, never licensed artifacts
or private attestation evidence.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attestation.models import Attestation
from app.modules.developer.schemas import (
    PartnerAttestationReportResponse,
    PartnerAttestationsResponse,
    PartnerFrameworkDetailResponse,
    PartnerPreviewArtifactResponse,
)
from app.modules.explore import service as explore_service
from app.modules.explore.schemas import (
    ExploreAttestationStatus,
    ExploreFrameworkListResponse,
    ExploreSort,
)
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact


async def list_catalog(
    db: AsyncSession,
    *,
    q: str | None,
    page: int,
    page_size: int,
    sort: ExploreSort,
    sector: str | None,
    industry: str | None,
    function: str | None,
    category: str | None,
    license_type: str | None,
    complexity: int | None,
    org_size: str | None,
    lifecycle_stage: str | None,
    jurisdiction: str | None,
    price_min: Decimal | None,
    price_max: Decimal | None,
    attestation_status: ExploreAttestationStatus | None,
) -> ExploreFrameworkListResponse:
    """Return published Framework catalog results for Partner API consumers."""
    return await explore_service.list_catalog(
        db,
        current_user_id=None,
        q=q,
        page=page,
        page_size=page_size,
        sort=sort,
        sector=sector,
        industry=industry,
        function=function,
        category=category,
        license_type=license_type,
        complexity=complexity,
        org_size=org_size,
        lifecycle_stage=lifecycle_stage,
        jurisdiction=jurisdiction,
        price_min=price_min,
        price_max=price_max,
        attestation_status=attestation_status,
    )


async def get_detail(
    db: AsyncSession,
    *,
    framework_id: UUID,
) -> PartnerFrameworkDetailResponse:
    """Return Partner-safe public detail for one published Framework."""
    framework = await db.scalar(
        select(Framework).where(
            Framework.id == framework_id,
            Framework.status == "published",
        )
    )
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    rarity_scores = await explore_service._framework_rarity_scores(  # noqa: SLF001
        db,
        [framework.id],
    )
    attestation_badges = await explore_service._framework_attestation_badges(  # noqa: SLF001
        db,
        [framework.id],
    )
    review_aggregates = await explore_service._framework_review_aggregates(  # noqa: SLF001
        db,
        [framework.id],
    )
    contributor_names = await explore_service._user_display_names(  # noqa: SLF001
        db,
        [framework.contributor_id],
    )
    card = explore_service._card_from_framework(  # noqa: SLF001
        framework,
        rarity_scores.get(framework.id),
        attestation_badges.get(framework.id),
        review_aggregates.get(framework.id),
        contributor_names.get(framework.contributor_id, "Contributor"),
    )
    return PartnerFrameworkDetailResponse(
        **card.model_dump(),
        preview_artifact_id=framework.preview_artifact_id,
    )


async def get_preview(
    db: AsyncSession,
    redis: Redis,
    *,
    framework_id: UUID,
    client_ip: str,
) -> PartnerPreviewArtifactResponse:
    """Return the designated preview Artifact and URL for a published Framework."""
    framework = await db.scalar(
        select(Framework).where(
            Framework.id == framework_id,
            Framework.status == "published",
        )
    )
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    if framework.preview_artifact_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preview artifact not found.",
        )
    preview_artifact = await db.scalar(
        select(Artifact).where(
            Artifact.id == framework.preview_artifact_id,
            Artifact.framework_id == framework.id,
            Artifact.current_for_framework.is_(True),
        )
    )
    if preview_artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preview artifact not found.",
        )
    preview_url = await explore_service._preview_url(  # noqa: SLF001
        redis,
        framework,
        preview_artifact,
        client_ip,
    )
    if preview_url is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preview artifact not found.",
        )
    return PartnerPreviewArtifactResponse(
        id=preview_artifact.id,
        name=preview_artifact.name,
        file_size=preview_artifact.file_size,
        mime_type=preview_artifact.mime_type,
        preview_url=preview_url,
        created_at=preview_artifact.created_at,
    )


async def list_attestations(
    db: AsyncSession,
    *,
    framework_id: UUID,
) -> PartnerAttestationsResponse:
    """Return public Attestation report metadata for one published Framework."""
    framework_exists = await db.scalar(
        select(Framework.id).where(
            Framework.id == framework_id,
            Framework.status == "published",
        )
    )
    if framework_exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    rows = await db.execute(
        select(Attestation)
        .where(
            Attestation.target_type == "framework",
            Attestation.target_id == framework_id,
            Attestation.outcome.in_(
                explore_service.PUBLIC_POSITIVE_ATTESTATION_OUTCOMES
            ),
            Attestation.report_key.is_not(None),
            Attestation.status.in_(explore_service.PUBLIC_ATTESTATION_REPORT_STATUSES),
        )
        .order_by(
            Attestation.issued_at.desc().nullslast(),
            Attestation.created_at.desc(),
        )
    )
    return PartnerAttestationsResponse(
        attestations=[
            PartnerAttestationReportResponse(
                id=attestation.id,
                status=attestation.status,
                outcome=attestation.outcome,
                report_key=attestation.report_key,
                issued_at=attestation.issued_at,
            )
            for attestation in rows.scalars().all()
        ]
    )
