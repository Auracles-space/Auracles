"""Service logic for public Explore marketplace reads."""

from __future__ import annotations

from collections.abc import Awaitable
from decimal import Decimal
from typing import cast
from uuid import UUID

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations import s3
from app.modules.explore.schemas import (
    ExploreArtifactSummary,
    ExploreFrameworkCard,
    ExploreFrameworkDetail,
    ExploreFrameworkListResponse,
    ExploreSort,
)
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact

PREVIEW_URL_TTL_SECONDS = 900
PREVIEW_RATE_LIMIT = 60
PREVIEW_RATE_LIMIT_WINDOW_SECONDS = 60


def _card_from_framework(
    framework: Framework,
    rarity_score: Decimal | None,
) -> ExploreFrameworkCard:
    """Map a published Framework row into a public catalog card."""
    return ExploreFrameworkCard(
        id=framework.id,
        title=framework.title,
        description=framework.description,
        version=framework.version,
        category=framework.category,
        sector=framework.sector,
        industry=framework.industry,
        function=framework.business_function,
        tags=framework.tags,
        jurisdiction=framework.jurisdiction,
        complexity=framework.complexity,
        org_size=framework.org_size,
        lifecycle_stage=framework.lifecycle_stage,
        price=framework.price,
        currency=framework.currency,
        license_types=framework.license_types,
        thumbnail_key=framework.thumbnail_key,
        rarity_score=rarity_score,
        owned=False,
        published_at=framework.published_at,
    )


def _search_match(framework: Framework, query: str) -> bool:
    """Return whether a Framework matches simple fallback text search."""
    normalized = query.lower()
    haystack = " ".join(
        [
            framework.title,
            framework.description,
            framework.tags_text,
            " ".join(framework.tags),
        ]
    ).lower()
    return normalized in haystack


def _base_catalog_query(current_user_id: UUID | None) -> Select[tuple[Framework]]:
    """Build the base query for public catalog reads."""
    query = select(Framework).where(Framework.status == "published")
    if current_user_id is not None:
        query = query.where(Framework.contributor_id != current_user_id)
    return query


def _apply_filters(
    query: Select[tuple[Framework]],
    *,
    q: str | None,
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
) -> Select[tuple[Framework]]:
    """Apply faceted Explore filters to the catalog query."""
    if q:
        query = query.where(
            or_(
                Framework.title.ilike(f"%{q}%"),
                Framework.description.ilike(f"%{q}%"),
                Framework.tags_text.ilike(f"%{q}%"),
            )
        )
    if sector:
        query = query.where(Framework.sector == sector)
    if industry:
        query = query.where(Framework.industry == industry)
    if function:
        query = query.where(Framework.business_function == function)
    if category:
        query = query.where(Framework.category == category)
    if license_type:
        query = query.where(Framework.license_types.contains([license_type]))
    if complexity is not None:
        query = query.where(Framework.complexity == complexity)
    if org_size:
        query = query.where(Framework.org_size == org_size)
    if lifecycle_stage:
        query = query.where(Framework.lifecycle_stage == lifecycle_stage)
    if jurisdiction:
        query = query.where(Framework.jurisdiction == jurisdiction)
    if price_min is not None:
        query = query.where(Framework.price >= price_min)
    if price_max is not None:
        query = query.where(Framework.price <= price_max)
    return query


def _apply_sort(
    query: Select[tuple[Framework]],
    sort: ExploreSort,
) -> Select[tuple[Framework]]:
    """Apply stable catalog ordering."""
    if sort == "price_asc":
        return query.order_by(Framework.price.asc(), Framework.created_at.desc())
    if sort == "price_desc":
        return query.order_by(Framework.price.desc(), Framework.created_at.desc())
    return query.order_by(Framework.published_at.desc(), Framework.created_at.desc())


async def _framework_rarity_scores(
    db: AsyncSession,
    framework_ids: list[UUID],
) -> dict[UUID, Decimal | None]:
    """Return max current Artifact rarity by Framework."""
    if not framework_ids:
        return {}
    rows = await db.execute(
        select(Artifact.framework_id, func.max(Artifact.rarity_score))
        .where(
            Artifact.framework_id.in_(framework_ids),
            Artifact.current_for_framework.is_(True),
        )
        .group_by(Artifact.framework_id)
    )
    return {framework_id: rarity_score for framework_id, rarity_score in rows.all()}


async def list_catalog(
    db: AsyncSession,
    *,
    current_user_id: UUID | None,
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
) -> ExploreFrameworkListResponse:
    """Return published Frameworks for public Explore."""
    query = _apply_filters(
        _base_catalog_query(current_user_id),
        q=q,
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
    )
    count_query = select(func.count()).select_from(query.subquery())
    total = int(await db.scalar(count_query) or 0)
    offset = (page - 1) * page_size
    rows = await db.execute(_apply_sort(query, sort).offset(offset).limit(page_size))
    frameworks = list(rows.scalars().all())
    rarity_scores = await _framework_rarity_scores(
        db,
        [framework.id for framework in frameworks],
    )
    return ExploreFrameworkListResponse(
        items=[
            _card_from_framework(framework, rarity_scores.get(framework.id))
            for framework in frameworks
        ],
        total=total,
        page=page,
        page_size=page_size,
        sort=sort,
        sort_shim=sort in {"top-rated", "most-purchased"},
    )


async def _enforce_preview_rate_limit(redis: Redis, client_ip: str) -> None:
    """Apply a fixed-window rate limit for public preview URL generation."""
    key = f"preview_url:{client_ip}"
    count = await cast(Awaitable[int], redis.incr(key))
    if count == 1:
        await redis.expire(key, PREVIEW_RATE_LIMIT_WINDOW_SECONDS)
    if count > PREVIEW_RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Preview rate limit exceeded.",
        )


async def _preview_url(
    redis: Redis,
    framework: Framework,
    preview_artifact: Artifact | None,
    client_ip: str,
) -> str | None:
    """Return a presigned preview URL for the designated preview Artifact."""
    if framework.preview_artifact_id is None or preview_artifact is None:
        return None
    await _enforce_preview_rate_limit(redis, client_ip)
    settings = get_settings()
    return s3.storage.presigned_get(
        settings.s3_artifacts_bucket,
        preview_artifact.file_key,
        PREVIEW_URL_TTL_SECONDS,
    )


async def get_detail(
    db: AsyncSession,
    redis: Redis,
    *,
    framework_id: UUID,
    current_user_id: UUID | None,
    client_ip: str,
) -> ExploreFrameworkDetail:
    """Return public detail for one published Framework."""
    framework = await db.scalar(
        _base_catalog_query(current_user_id).where(Framework.id == framework_id)
    )
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    artifact_rows = (
        await db.execute(
            select(Artifact)
            .where(
                Artifact.framework_id == framework.id,
                Artifact.current_for_framework.is_(True),
            )
            .order_by(Artifact.created_at)
        )
    ).scalars().all()
    artifacts = list(artifact_rows)
    rarity_scores = await _framework_rarity_scores(db, [framework.id])
    preview_artifact = next(
        (
            artifact
            for artifact in artifacts
            if artifact.id == framework.preview_artifact_id
        ),
        None,
    )
    card = _card_from_framework(framework, rarity_scores.get(framework.id))
    return ExploreFrameworkDetail(
        **card.model_dump(),
        preview_artifact_id=framework.preview_artifact_id,
        preview_url=await _preview_url(redis, framework, preview_artifact, client_ip),
        artifacts=[
            ExploreArtifactSummary(
                id=artifact.id,
                name=artifact.name,
                file_size=artifact.file_size,
                mime_type=artifact.mime_type,
                created_at=artifact.created_at,
            )
            for artifact in artifacts
        ],
    )


def _related_score(source: Framework, candidate: Framework) -> tuple[int, str]:
    """Return a deterministic relevance score for related Framework sorting."""
    source_tags = {tag.lower() for tag in source.tags}
    candidate_tags = {tag.lower() for tag in candidate.tags}
    score = len(source_tags.intersection(candidate_tags)) * 3
    if source.category == candidate.category:
        score += 2
    if source.sector == candidate.sector:
        score += 1
    if source.industry == candidate.industry:
        score += 1
    if _search_match(candidate, source.title):
        score += 1
    return (score, candidate.title.lower())


async def related_frameworks(
    db: AsyncSession,
    *,
    framework_id: UUID,
    current_user_id: UUID | None,
) -> list[ExploreFrameworkCard]:
    """Return up to six related published Frameworks."""
    source = await db.scalar(
        select(Framework).where(
            Framework.id == framework_id,
            Framework.status == "published",
        )
    )
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )

    candidate_query = _base_catalog_query(current_user_id).where(
        Framework.id != framework_id
    )
    rows = await db.execute(candidate_query)
    candidates = list(rows.scalars().all())
    ranked = sorted(
        candidates,
        key=lambda candidate: _related_score(source, candidate),
        reverse=True,
    )[:6]
    rarity_scores = await _framework_rarity_scores(
        db,
        [framework.id for framework in ranked],
    )
    return [
        _card_from_framework(framework, rarity_scores.get(framework.id))
        for framework in ranked
    ]
