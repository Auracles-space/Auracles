"""FastAPI router for public marketplace Explore endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError  # type: ignore[import-untyped]
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import decode_access_token
from app.modules.explore import service
from app.modules.explore.schemas import (
    ExploreAttestationStatus,
    ExploreCatalogResponse,
    ExploreCollectionDetail,
    ExploreCollectionListResponse,
    ExploreContributorProfile,
    ExploreFrameworkCard,
    ExploreFrameworkDetail,
    ExploreFrameworkListResponse,
    ExploreSort,
)

router = APIRouter(prefix="/explore", tags=["Explore"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
optional_bearer = HTTPBearer(auto_error=False)


async def optional_current_user_id(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(optional_bearer),
    ],
) -> UUID | None:
    """Return the token user id when a valid bearer token is present."""
    if credentials is None:
        return None
    try:
        return decode_access_token(credentials.credentials).sub
    except JWTError:
        return None


@router.get("/frameworks", response_model=ExploreFrameworkListResponse)
async def list_frameworks(
    response: Response,
    db: DatabaseSession,
    current_user_id: Annotated[UUID | None, Depends(optional_current_user_id)],
    q: str | None = Query(default=None, min_length=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort: ExploreSort = "newest",
    sector: str | None = None,
    industry: str | None = None,
    function: str | None = None,
    category: str | None = None,
    license_type: str | None = None,
    complexity: int | None = Query(default=None, ge=1, le=5),
    org_size: str | None = None,
    lifecycle_stage: str | None = None,
    jurisdiction: str | None = None,
    price_min: Annotated[Decimal | None, Query(ge=0)] = None,
    price_max: Annotated[Decimal | None, Query(ge=0)] = None,
    attestation_status: ExploreAttestationStatus | None = None,
) -> ExploreFrameworkListResponse:
    """Return paginated public Framework catalog results."""
    result = await service.list_catalog(
        db,
        current_user_id=current_user_id,
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
    if result.sort_shim:
        response.headers["X-Sort-Shim"] = "true"
    return result


@router.get("/catalog", response_model=ExploreCatalogResponse)
async def list_mixed_catalog(
    db: DatabaseSession,
    current_user_id: Annotated[UUID | None, Depends(optional_current_user_id)],
    q: str | None = Query(default=None, min_length=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort: ExploreSort = "newest",
    sector: str | None = None,
    industry: str | None = None,
    function: str | None = None,
    category: str | None = None,
    license_type: str | None = None,
    complexity: int | None = Query(default=None, ge=1, le=5),
    org_size: str | None = None,
    lifecycle_stage: str | None = None,
    jurisdiction: str | None = None,
    price_min: Annotated[Decimal | None, Query(ge=0)] = None,
    price_max: Annotated[Decimal | None, Query(ge=0)] = None,
    attestation_status: ExploreAttestationStatus | None = None,
) -> ExploreCatalogResponse:
    """Return paginated public Framework and Collection catalog results.

    Framework taxonomy filters narrow Framework cards and exclude Collections
    (bundles carry no taxonomy); ``q`` and price filters apply to both.
    """
    return await service.list_mixed_catalog(
        db,
        current_user_id=current_user_id,
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


@router.get("/collections", response_model=ExploreCollectionListResponse)
async def list_collections(
    db: DatabaseSession,
    current_user_id: Annotated[UUID | None, Depends(optional_current_user_id)],
    q: str | None = Query(default=None, min_length=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort: ExploreSort = "newest",
    price_min: Annotated[Decimal | None, Query(ge=0)] = None,
    price_max: Annotated[Decimal | None, Query(ge=0)] = None,
) -> ExploreCollectionListResponse:
    """Return paginated public Collection catalog results."""
    return await service.list_collections(
        db,
        current_user_id=current_user_id,
        q=q,
        page=page,
        page_size=page_size,
        sort=sort,
        price_min=price_min,
        price_max=price_max,
    )


@router.get("/collections/{collection_id}", response_model=ExploreCollectionDetail)
async def get_collection_detail(
    collection_id: UUID,
    db: DatabaseSession,
    current_user_id: Annotated[UUID | None, Depends(optional_current_user_id)],
) -> ExploreCollectionDetail:
    """Return public detail for one published Collection."""
    return await service.get_collection_detail(
        db,
        collection_id=collection_id,
        current_user_id=current_user_id,
    )


@router.get(
    "/contributors/{contributor_id}",
    response_model=ExploreContributorProfile,
)
async def get_contributor_profile(
    contributor_id: UUID,
    db: DatabaseSession,
) -> ExploreContributorProfile:
    """Return a public Contributor profile and published Frameworks."""
    return await service.get_contributor_profile(
        db,
        contributor_id=contributor_id,
    )


@router.get("/frameworks/{framework_id}", response_model=ExploreFrameworkDetail)
async def get_framework_detail(
    framework_id: UUID,
    request: Request,
    db: DatabaseSession,
    redis: RedisClient,
    current_user_id: Annotated[UUID | None, Depends(optional_current_user_id)],
) -> ExploreFrameworkDetail:
    """Return public detail for one published Framework."""
    return await service.get_detail(
        db,
        redis,
        framework_id=framework_id,
        current_user_id=current_user_id,
        client_ip=request.client.host if request.client else "unknown",
    )


@router.get(
    "/frameworks/{framework_id}/related",
    response_model=list[ExploreFrameworkCard],
)
async def get_related_frameworks(
    framework_id: UUID,
    db: DatabaseSession,
    current_user_id: Annotated[UUID | None, Depends(optional_current_user_id)],
) -> list[ExploreFrameworkCard]:
    """Return related published Frameworks for a public detail page."""
    return await service.related_frameworks(
        db,
        framework_id=framework_id,
        current_user_id=current_user_id,
    )
