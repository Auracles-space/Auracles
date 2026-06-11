"""Service logic for public Explore marketplace reads."""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import Select, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import get_settings
from app.integrations import s3
from app.modules.attestation.models import Attestation
from app.modules.auth.models import User, UserRole
from app.modules.collections.models import CollectionFramework, FrameworkCollection
from app.modules.explore.schemas import (
    ExploreArtifactSummary,
    ExploreAttestationBadge,
    ExploreAttestationStatus,
    ExploreCatalogItem,
    ExploreCatalogResponse,
    ExploreCollectionCard,
    ExploreCollectionDetail,
    ExploreCollectionListResponse,
    ExploreCollectionMemberSummary,
    ExploreContributorProfile,
    ExploreFrameworkCard,
    ExploreFrameworkCatalogItem,
    ExploreFrameworkDetail,
    ExploreFrameworkListResponse,
    ExploreSort,
)
from app.modules.frameworks.models import Framework, License, Review
from app.modules.frameworks.models_artifact import Artifact

PREVIEW_URL_TTL_SECONDS = 900
PREVIEW_RATE_LIMIT = 60
PREVIEW_RATE_LIMIT_WINDOW_SECONDS = 60
PUBLIC_POSITIVE_ATTESTATION_OUTCOMES = ("approved", "conditional")
PUBLIC_ATTESTATION_REPORT_STATUSES = ("report_submitted", "closed")


def _card_from_framework(
    framework: Framework,
    rarity_score: Decimal | None,
    attestation_badge: ExploreAttestationBadge | None,
    review_aggregate: tuple[Decimal | None, int] | None,
    contributor_name: str,
) -> ExploreFrameworkCard:
    """Map a published Framework row into a public catalog card."""
    average_review_score, review_count = review_aggregate or (None, 0)
    return ExploreFrameworkCard(
        id=framework.id,
        contributor_id=framework.contributor_id,
        contributor_name=contributor_name,
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
        average_review_score=average_review_score,
        review_count=review_count,
        attestation_badge=attestation_badge,
        owned=False,
        published_at=framework.published_at,
    )


def _catalog_item_from_framework_card(
    card: ExploreFrameworkCard,
) -> ExploreFrameworkCatalogItem:
    """Add the mixed-catalog discriminator to an existing Framework card."""
    return ExploreFrameworkCatalogItem(**card.model_dump(), item_type="framework")


def _collection_search_match(collection: FrameworkCollection, query: str) -> bool:
    """Return whether a Collection matches simple public text search."""
    normalized = query.lower()
    haystack = " ".join([collection.title, collection.description]).lower()
    return normalized in haystack


def _collection_member_summary(framework: Framework) -> ExploreCollectionMemberSummary:
    """Map a member Framework to the public Collection member summary."""
    return ExploreCollectionMemberSummary(
        framework_id=framework.id,
        title=framework.title,
        version=framework.version,
        category=framework.category,
        price=framework.price,
        currency=framework.currency,
        thumbnail_key=framework.thumbnail_key,
    )


async def _collection_members(
    db: AsyncSession,
    collection_id: UUID,
) -> list[Framework]:
    """Return member Frameworks for a public Collection card."""
    rows = await db.execute(
        select(Framework)
        .join(CollectionFramework, CollectionFramework.framework_id == Framework.id)
        .where(CollectionFramework.collection_id == collection_id)
        .order_by(Framework.title.asc(), Framework.id.asc())
    )
    return list(rows.scalars().all())


def _collection_savings(
    *,
    collection: FrameworkCollection,
    members: list[Framework],
) -> tuple[Decimal, Decimal, Decimal]:
    """Return current member sum, savings amount, and percentage for a bundle."""
    member_price_sum = sum((member.price for member in members), Decimal("0.00"))
    savings_amount = member_price_sum - collection.bundle_price
    if member_price_sum <= 0:
        return member_price_sum, savings_amount, Decimal("0.00")
    savings_percent = (
        (savings_amount / member_price_sum) * Decimal("100")
    ).quantize(Decimal("0.01"))
    return member_price_sum, savings_amount, savings_percent


async def _card_from_collection(
    db: AsyncSession,
    collection: FrameworkCollection,
    contributor_name: str,
) -> ExploreCollectionCard:
    """Map a published Collection row into a public catalog card."""
    members = await _collection_members(db, collection.id)
    member_price_sum, savings_amount, savings_percent = _collection_savings(
        collection=collection,
        members=members,
    )
    return ExploreCollectionCard(
        id=collection.id,
        contributor_id=collection.contributor_id,
        contributor_name=contributor_name,
        title=collection.title,
        description=collection.description,
        bundle_price=collection.bundle_price,
        currency=collection.currency,
        member_price_sum=member_price_sum,
        savings_amount=savings_amount,
        savings_percent=savings_percent,
        member_count=len(members),
        members=[_collection_member_summary(member) for member in members],
        created_at=collection.created_at,
        updated_at=collection.updated_at,
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
    attestation_status: ExploreAttestationStatus | None,
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
    if attestation_status is not None:
        query = _apply_attestation_filter(query, attestation_status)
    return query


def _public_attestation_exists(
    *,
    status_: str | None = None,
    outcome: str | None = None,
) -> ColumnElement[bool]:
    """Build an EXISTS predicate for public Framework Attestation reports."""
    predicate = (
        select(Attestation.id)
        .where(
            Attestation.target_type == "framework",
            Attestation.target_id == Framework.id,
            # Public badges are positive trust signals; rejected reports remain
            # available to future report views but must not render as attested.
            Attestation.outcome.in_(PUBLIC_POSITIVE_ATTESTATION_OUTCOMES),
            Attestation.report_key.is_not(None),
            Attestation.status.in_(PUBLIC_ATTESTATION_REPORT_STATUSES),
        )
        .limit(1)
    )
    if status_ is not None:
        predicate = predicate.where(Attestation.status == status_)
    if outcome is not None:
        predicate = predicate.where(Attestation.outcome == outcome)
    return predicate.exists()


def _apply_attestation_filter(
    query: Select[tuple[Framework]],
    attestation_status: ExploreAttestationStatus,
) -> Select[tuple[Framework]]:
    """Apply public Attestation badge filters to the catalog query."""
    if attestation_status == "pending_acceptance":
        return query.where(_public_attestation_exists(status_="report_submitted"))
    if attestation_status == "attested":
        return query.where(
            _public_attestation_exists(status_="closed", outcome="approved")
        )
    if attestation_status == "conditionally_attested":
        return query.where(
            _public_attestation_exists(status_="closed", outcome="conditional")
        )
    return query.where(~_public_attestation_exists())


def _apply_sort(
    query: Select[tuple[Framework]],
    sort: ExploreSort,
) -> Select[tuple[Framework]]:
    """Apply stable catalog ordering."""
    if sort == "top-rated":
        average_score = (
            select(func.avg(Review.score))
            .where(Review.framework_id == Framework.id)
            .correlate(Framework)
            .scalar_subquery()
        )
        review_count = (
            select(func.count(Review.id))
            .where(Review.framework_id == Framework.id)
            .correlate(Framework)
            .scalar_subquery()
        )
        return query.order_by(
            average_score.desc().nullslast(),
            review_count.desc(),
            Framework.published_at.desc(),
            Framework.created_at.desc(),
        )
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


async def _framework_review_aggregates(
    db: AsyncSession,
    framework_ids: list[UUID],
) -> dict[UUID, tuple[Decimal | None, int]]:
    """Return average review score and count by Framework id."""
    if not framework_ids:
        return {}
    rows = await db.execute(
        select(
            Review.framework_id,
            func.avg(Review.score),
            func.count(Review.id),
        )
        .where(Review.framework_id.in_(framework_ids))
        .group_by(Review.framework_id)
    )
    aggregates: dict[UUID, tuple[Decimal | None, int]] = {}
    for framework_id, average_score, review_count in rows.all():
        rounded_score = (
            Decimal(average_score).quantize(Decimal("0.01"))
            if average_score is not None
            else None
        )
        aggregates[framework_id] = (rounded_score, int(review_count))
    return aggregates


async def _user_display_names(
    db: AsyncSession,
    user_ids: list[UUID],
) -> dict[UUID, str]:
    """Return public display names keyed by user id."""
    if not user_ids:
        return {}
    rows = await db.execute(
        select(User.id, User.display_name).where(User.id.in_(user_ids))
    )
    return {user_id: display_name for user_id, display_name in rows.all()}


def _public_attestation_status(status_: str, outcome: str | None) -> str | None:
    """Map an internal Attestation report to a positive public badge status."""
    if outcome not in PUBLIC_POSITIVE_ATTESTATION_OUTCOMES:
        return None
    if status_ == "report_submitted":
        return "pending_acceptance"
    if status_ == "closed" and outcome == "approved":
        return "attested"
    if status_ == "closed" and outcome == "conditional":
        return "conditionally_attested"
    return None


def _public_attestation_rank(status_: str, outcome: str | None) -> int | None:
    """Return lower-is-better public badge ranking for one Attestation."""
    public_status = _public_attestation_status(status_, outcome)
    if public_status == "attested":
        return 0
    if public_status == "conditionally_attested":
        return 1
    if public_status == "pending_acceptance" and outcome == "approved":
        return 2
    if public_status == "pending_acceptance" and outcome == "conditional":
        return 3
    return None


def _attestation_is_better(
    candidate: tuple[int, Attestation],
    current: tuple[int, Attestation],
) -> bool:
    """Return whether candidate should replace current selected public badge."""
    candidate_rank, candidate_attestation = candidate
    current_rank, current_attestation = current
    if candidate_rank != current_rank:
        return candidate_rank < current_rank
    candidate_time = candidate_attestation.issued_at or candidate_attestation.created_at
    current_time = current_attestation.issued_at or current_attestation.created_at
    return candidate_time > current_time


async def _public_attestation_badges(
    db: AsyncSession,
    *,
    target_type: str,
    target_ids: list[UUID],
) -> tuple[dict[UUID, ExploreAttestationBadge], dict[UUID, int]]:
    """Return best public Attestation badge and report count per target."""
    if not target_ids:
        return {}, {}
    rows = (
        await db.execute(
            select(Attestation)
            .where(
                Attestation.target_type == target_type,
                Attestation.target_id.in_(target_ids),
                Attestation.outcome.is_not(None),
                Attestation.report_key.is_not(None),
                Attestation.status.in_(PUBLIC_ATTESTATION_REPORT_STATUSES),
            )
        )
    ).scalars()
    selected: dict[UUID, tuple[int, Attestation]] = {}
    counts: dict[UUID, int] = {}
    for attestation in rows:
        counts[attestation.target_id] = counts.get(attestation.target_id, 0) + 1
        rank = _public_attestation_rank(attestation.status, attestation.outcome)
        if rank is None:
            continue
        current = selected.get(attestation.target_id)
        candidate = (rank, attestation)
        if current is None or _attestation_is_better(candidate, current):
            selected[attestation.target_id] = candidate

    badges: dict[UUID, ExploreAttestationBadge] = {}
    for target_id, (_, attestation) in selected.items():
        public_status = _public_attestation_status(
            attestation.status,
            attestation.outcome,
        )
        if public_status is None:
            continue
        badges[target_id] = ExploreAttestationBadge(
            id=attestation.id,
            status=public_status,
            outcome=attestation.outcome,
            report_key=attestation.report_key,
            issued_at=attestation.issued_at,
            attestation_count=counts.get(target_id, 0),
        )
    return badges, counts


async def _framework_attestation_badges(
    db: AsyncSession,
    framework_ids: list[UUID],
) -> dict[UUID, ExploreAttestationBadge]:
    """Return best public Attestation badge per Framework."""
    badges, _ = await _public_attestation_badges(
        db,
        target_type="framework",
        target_ids=framework_ids,
    )
    return badges


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
    attestation_status: ExploreAttestationStatus | None,
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
        attestation_status=attestation_status,
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
    attestation_badges = await _framework_attestation_badges(
        db,
        [framework.id for framework in frameworks],
    )
    review_aggregates = await _framework_review_aggregates(
        db,
        [framework.id for framework in frameworks],
    )
    contributor_names = await _user_display_names(
        db,
        [framework.contributor_id for framework in frameworks],
    )
    return ExploreFrameworkListResponse(
        items=[
            _card_from_framework(
                framework,
                rarity_scores.get(framework.id),
                attestation_badges.get(framework.id),
                review_aggregates.get(framework.id),
                contributor_names.get(framework.contributor_id, "Contributor"),
            )
            for framework in frameworks
        ],
        total=total,
        page=page,
        page_size=page_size,
        sort=sort,
        sort_shim=sort == "most-purchased",
    )


def _base_collection_query(
    current_user_id: UUID | None,
) -> Select[tuple[FrameworkCollection]]:
    """Build the base query for public Collection catalog reads."""
    query = select(FrameworkCollection).where(FrameworkCollection.status == "published")
    if current_user_id is not None:
        query = query.where(FrameworkCollection.contributor_id != current_user_id)
    return query


def _apply_collection_filters(
    query: Select[tuple[FrameworkCollection]],
    *,
    q: str | None,
    price_min: Decimal | None = None,
    price_max: Decimal | None = None,
) -> Select[tuple[FrameworkCollection]]:
    """Apply public Collection filters supported by the MVP read model."""
    if q:
        query = query.where(
            or_(
                FrameworkCollection.title.ilike(f"%{q}%"),
                FrameworkCollection.description.ilike(f"%{q}%"),
            )
        )
    if price_min is not None:
        query = query.where(FrameworkCollection.bundle_price >= price_min)
    if price_max is not None:
        query = query.where(FrameworkCollection.bundle_price <= price_max)
    return query


def _apply_collection_sort(
    query: Select[tuple[FrameworkCollection]],
    sort: ExploreSort,
) -> Select[tuple[FrameworkCollection]]:
    """Apply stable public Collection ordering."""
    if sort == "price_asc":
        return query.order_by(
            FrameworkCollection.bundle_price.asc(),
            FrameworkCollection.updated_at.desc(),
        )
    if sort == "price_desc":
        return query.order_by(
            FrameworkCollection.bundle_price.desc(),
            FrameworkCollection.updated_at.desc(),
        )
    return query.order_by(
        FrameworkCollection.updated_at.desc(),
        FrameworkCollection.created_at.desc(),
    )


async def list_collections(
    db: AsyncSession,
    *,
    current_user_id: UUID | None,
    q: str | None,
    page: int,
    page_size: int,
    sort: ExploreSort,
    price_min: Decimal | None,
    price_max: Decimal | None,
) -> ExploreCollectionListResponse:
    """Return published Collections for public Explore."""
    query = _apply_collection_filters(
        _base_collection_query(current_user_id),
        q=q,
        price_min=price_min,
        price_max=price_max,
    )
    total = int(
        await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    )
    offset = (page - 1) * page_size
    rows = await db.execute(
        _apply_collection_sort(query, sort).offset(offset).limit(page_size)
    )
    collections = list(rows.scalars().all())
    contributor_names = await _user_display_names(
        db,
        [collection.contributor_id for collection in collections],
    )
    return ExploreCollectionListResponse(
        items=[
            await _card_from_collection(
                db,
                collection,
                contributor_names.get(collection.contributor_id, "Contributor"),
            )
            for collection in collections
        ],
        total=total,
        page=page,
        page_size=page_size,
        sort=sort,
        sort_shim=sort in {"most-purchased", "top-rated"},
    )


async def _already_owned_member_ids(
    db: AsyncSession,
    *,
    current_user_id: UUID | None,
    member_ids: list[UUID],
) -> list[UUID]:
    """Return active member Framework ids already licensed by the viewer."""
    if current_user_id is None or not member_ids:
        return []
    now = datetime.now(UTC)
    rows = await db.execute(
        select(License.framework_id).where(
            License.operator_id == current_user_id,
            License.framework_id.in_(member_ids),
            License.status == "active",
            or_(License.expires_at.is_(None), License.expires_at > now),
        )
    )
    return list(rows.scalars().all())


async def get_collection_detail(
    db: AsyncSession,
    *,
    collection_id: UUID,
    current_user_id: UUID | None,
) -> ExploreCollectionDetail:
    """Return public detail for one published Collection."""
    collection = await db.scalar(
        _base_collection_query(current_user_id).where(
            FrameworkCollection.id == collection_id
        )
    )
    if collection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found.",
        )
    contributor_names = await _user_display_names(db, [collection.contributor_id])
    card = await _card_from_collection(
        db,
        collection,
        contributor_names.get(collection.contributor_id, "Contributor"),
    )
    already_owned = await _already_owned_member_ids(
        db,
        current_user_id=current_user_id,
        member_ids=[member.framework_id for member in card.members],
    )
    return ExploreCollectionDetail(
        **card.model_dump(),
        already_owned_member_ids=already_owned,
    )


def _catalog_item_sort_key(
    item: ExploreCatalogItem,
    sort: ExploreSort,
) -> tuple[Decimal | datetime, datetime]:
    """Return a stable Python sort key for the mixed catalog."""
    if isinstance(item, ExploreFrameworkCatalogItem):
        price = item.price
        timestamp = item.published_at or datetime.min.replace(tzinfo=UTC)
    else:
        price = item.bundle_price
        timestamp = item.updated_at
    if sort in {"price_asc", "price_desc"}:
        return price, timestamp
    return timestamp, timestamp


async def list_mixed_catalog(
    db: AsyncSession,
    *,
    current_user_id: UUID | None,
    q: str | None,
    page: int,
    page_size: int,
    sort: ExploreSort,
) -> ExploreCatalogResponse:
    """Return Framework and Collection cards in one typed public catalog."""
    framework_query = _apply_filters(
        _base_catalog_query(current_user_id),
        q=q,
        sector=None,
        industry=None,
        function=None,
        category=None,
        license_type=None,
        complexity=None,
        org_size=None,
        lifecycle_stage=None,
        jurisdiction=None,
        price_min=None,
        price_max=None,
        attestation_status=None,
    )
    framework_rows = await db.execute(framework_query)
    frameworks = list(framework_rows.scalars().all())
    rarity_scores = await _framework_rarity_scores(
        db,
        [framework.id for framework in frameworks],
    )
    attestation_badges = await _framework_attestation_badges(
        db,
        [framework.id for framework in frameworks],
    )
    review_aggregates = await _framework_review_aggregates(
        db,
        [framework.id for framework in frameworks],
    )
    framework_contributor_names = await _user_display_names(
        db,
        [framework.contributor_id for framework in frameworks],
    )
    framework_items: list[ExploreCatalogItem] = [
        _catalog_item_from_framework_card(
            _card_from_framework(
                framework,
                rarity_scores.get(framework.id),
                attestation_badges.get(framework.id),
                review_aggregates.get(framework.id),
                framework_contributor_names.get(
                    framework.contributor_id,
                    "Contributor",
                ),
            )
        )
        for framework in frameworks
    ]

    collection_query = _apply_collection_filters(
        _base_collection_query(current_user_id),
        q=q,
    )
    collection_rows = await db.execute(collection_query)
    collections = list(collection_rows.scalars().all())
    collection_contributor_names = await _user_display_names(
        db,
        [collection.contributor_id for collection in collections],
    )
    collection_items: list[ExploreCatalogItem] = [
        await _card_from_collection(
            db,
            collection,
            collection_contributor_names.get(
                collection.contributor_id,
                "Contributor",
            ),
        )
        for collection in collections
    ]
    items = framework_items + collection_items
    reverse = sort not in {"price_asc"}
    items = sorted(
        items,
        key=lambda item: _catalog_item_sort_key(item, sort),
        reverse=reverse,
    )
    offset = (page - 1) * page_size
    return ExploreCatalogResponse(
        items=items[offset : offset + page_size],
        total=len(items),
        page=page,
        page_size=page_size,
        sort=sort,
        sort_shim=sort in {"most-purchased", "top-rated"},
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
    attestation_badges = await _framework_attestation_badges(db, [framework.id])
    review_aggregates = await _framework_review_aggregates(db, [framework.id])
    contributor_names = await _user_display_names(db, [framework.contributor_id])
    preview_artifact = next(
        (
            artifact
            for artifact in artifacts
            if artifact.id == framework.preview_artifact_id
        ),
        None,
    )
    card = _card_from_framework(
        framework,
        rarity_scores.get(framework.id),
        attestation_badges.get(framework.id),
        review_aggregates.get(framework.id),
        contributor_names.get(framework.contributor_id, "Contributor"),
    )
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
    attestation_badges = await _framework_attestation_badges(
        db,
        [framework.id for framework in ranked],
    )
    review_aggregates = await _framework_review_aggregates(
        db,
        [framework.id for framework in ranked],
    )
    contributor_names = await _user_display_names(
        db,
        [framework.contributor_id for framework in ranked],
    )
    return [
        _card_from_framework(
            framework,
            rarity_scores.get(framework.id),
            attestation_badges.get(framework.id),
            review_aggregates.get(framework.id),
            contributor_names.get(framework.contributor_id, "Contributor"),
        )
        for framework in ranked
    ]


async def get_contributor_profile(
    db: AsyncSession,
    *,
    contributor_id: UUID,
) -> ExploreContributorProfile:
    """Return a public Contributor profile with published Framework cards."""
    contributor = await db.scalar(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .where(
            User.id == contributor_id,
            UserRole.role == "contributor",
        )
    )
    if contributor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contributor not found.",
        )

    published_count = int(
        await db.scalar(
            select(func.count(Framework.id)).where(
                Framework.contributor_id == contributor_id,
                Framework.status == "published",
            )
        )
        or 0
    )
    if published_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contributor not found.",
        )

    rows = await db.execute(
        select(Framework)
        .where(
            Framework.contributor_id == contributor_id,
            Framework.status == "published",
        )
        .order_by(desc(Framework.published_at).nullslast(), Framework.created_at.desc())
        .limit(12)
    )
    frameworks = list(rows.scalars().all())
    framework_ids = [framework.id for framework in frameworks]
    rarity_scores = await _framework_rarity_scores(db, framework_ids)
    attestation_badges = await _framework_attestation_badges(db, framework_ids)
    review_aggregates = await _framework_review_aggregates(db, framework_ids)
    contributor_badges, contributor_badge_counts = await _public_attestation_badges(
        db,
        target_type="contributor",
        target_ids=[contributor_id],
    )

    return ExploreContributorProfile(
        id=contributor.id,
        display_name=contributor.display_name,
        avatar_url=contributor.avatar_url,
        bio=contributor.bio,
        location=contributor.location,
        website=contributor.website,
        attestation_badge=contributor_badges.get(contributor_id),
        attestation_count=contributor_badge_counts.get(contributor_id, 0),
        is_deactivated=contributor.deactivated_at is not None,
        published_framework_count=published_count,
        published_frameworks=[
            _card_from_framework(
                framework,
                rarity_scores.get(framework.id),
                attestation_badges.get(framework.id),
                review_aggregates.get(framework.id),
                contributor.display_name,
            )
            for framework in frameworks
        ],
    )
