"""Partner API router secured by `X-API-Key` scopes."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.modules.developer import partner_service
from app.modules.developer.auth import PartnerApiContext, require_api_key_scope
from app.modules.developer.schemas import (
    PartnerAttestationsResponse,
    PartnerFrameworkDetailResponse,
    PartnerPreviewArtifactResponse,
    PartnerPurchaseRequest,
    PartnerPurchaseResponse,
    PartnerPurchaseStatusResponse,
)
from app.modules.explore.schemas import (
    ExploreAttestationStatus,
    ExploreFrameworkListResponse,
    ExploreSort,
)

router = APIRouter(prefix="/partner", tags=["Partner API"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
CatalogReadContext = Annotated[
    PartnerApiContext,
    Depends(require_api_key_scope("catalog:read")),
]
PreviewReadContext = Annotated[
    PartnerApiContext,
    Depends(require_api_key_scope("preview:read")),
]
AttestationsReadContext = Annotated[
    PartnerApiContext,
    Depends(require_api_key_scope("attestations:read")),
]
PurchaseWriteContext = Annotated[
    PartnerApiContext,
    Depends(require_api_key_scope("purchase:write")),
]


@router.get("/catalog", response_model=ExploreFrameworkListResponse)
async def list_partner_catalog(
    response: Response,
    db: DatabaseSession,
    context: CatalogReadContext,
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
    """Return published Framework catalog results for Partner API consumers."""
    del context
    result = await partner_service.list_catalog(
        db,
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


@router.get("/catalog/{framework_id}", response_model=PartnerFrameworkDetailResponse)
async def get_partner_framework_detail(
    framework_id: UUID,
    db: DatabaseSession,
    context: CatalogReadContext,
) -> PartnerFrameworkDetailResponse:
    """Return Partner-safe public detail for one published Framework."""
    del context
    return await partner_service.get_detail(db, framework_id=framework_id)


@router.get(
    "/catalog/{framework_id}/preview",
    response_model=PartnerPreviewArtifactResponse,
)
async def get_partner_framework_preview(
    framework_id: UUID,
    request: Request,
    db: DatabaseSession,
    redis: RedisClient,
    context: PreviewReadContext,
) -> PartnerPreviewArtifactResponse:
    """Return only the contributor-designated preview Artifact."""
    del context
    return await partner_service.get_preview(
        db,
        redis,
        framework_id=framework_id,
        client_ip=request.client.host if request.client else "unknown",
    )


@router.get(
    "/catalog/{framework_id}/attestations",
    response_model=PartnerAttestationsResponse,
)
async def list_partner_framework_attestations(
    framework_id: UUID,
    db: DatabaseSession,
    context: AttestationsReadContext,
) -> PartnerAttestationsResponse:
    """Return public Attestation report metadata for one published Framework."""
    del context
    return await partner_service.list_attestations(db, framework_id=framework_id)


@router.post(
    "/frameworks/{framework_id}/purchase",
    response_model=PartnerPurchaseResponse,
)
async def initiate_partner_framework_purchase(
    framework_id: UUID,
    payload: PartnerPurchaseRequest,
    db: DatabaseSession,
    redis: RedisClient,
    context: PurchaseWriteContext,
) -> PartnerPurchaseResponse:
    """Start Stripe checkout for a Partner-attributed Framework purchase."""
    return await partner_service.initiate_purchase(
        db,
        redis,
        context=context,
        framework_id=framework_id,
        payload=payload,
    )


@router.get(
    "/purchases/{transaction_id}",
    response_model=PartnerPurchaseStatusResponse,
)
async def get_partner_purchase_status(
    transaction_id: UUID,
    db: DatabaseSession,
    context: PurchaseWriteContext,
) -> PartnerPurchaseStatusResponse:
    """Return status for a purchase created by the same Partner API key."""
    return await partner_service.get_purchase_status(
        db,
        context=context,
        transaction_id=transaction_id,
    )
