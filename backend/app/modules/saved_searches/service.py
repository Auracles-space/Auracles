"""Service layer for Operator saved searches.

Handles owner-scoped CRUD, Explore filter normalization, duplicate-name checks,
per-user limits, and audit logging for Phase 5b-2 discovery polish.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.auth.models import User
from app.modules.explore import service as explore_service
from app.modules.explore.schemas import (
    ExploreFrameworkListResponse,
    ExploreSearchFilters,
)
from app.modules.saved_searches.models import SavedSearch
from app.modules.saved_searches.schemas import (
    SavedSearchCreateRequest,
    SavedSearchListResponse,
    SavedSearchResponse,
    SavedSearchUpdateRequest,
)

MAX_SAVED_SEARCHES_PER_USER = 25


def _normalise_name(name: str) -> str:
    """Return a trimmed saved-search name or raise 422 when blank."""
    normalised = name.strip()
    if not normalised:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Saved search name cannot be blank.",
        )
    return normalised


def _normalise_filters(filters: ExploreSearchFilters) -> dict[str, Any]:
    """Serialize validated Explore filters for JSONB persistence."""
    return filters.model_dump(mode="json", exclude_none=True)


def _to_response(saved_search: SavedSearch) -> SavedSearchResponse:
    """Map a SavedSearch ORM row into an API response."""
    return SavedSearchResponse.model_validate(saved_search)


async def _load_owned_saved_search(
    db: AsyncSession,
    *,
    user_id: UUID,
    saved_search_id: UUID,
) -> SavedSearch:
    """Load an owned saved search or raise 404."""
    saved_search = await db.scalar(
        select(SavedSearch).where(
            SavedSearch.id == saved_search_id,
            SavedSearch.user_id == user_id,
        )
    )
    if saved_search is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved search not found.",
        )
    return saved_search


async def _ensure_name_available(
    db: AsyncSession,
    *,
    user_id: UUID,
    name: str,
    excluding_id: UUID | None = None,
) -> None:
    """Reject duplicate saved-search names for one Operator."""
    query = select(SavedSearch.id).where(
        SavedSearch.user_id == user_id,
        SavedSearch.name == name,
    )
    if excluding_id is not None:
        query = query.where(SavedSearch.id != excluding_id)
    existing_id = await db.scalar(query.limit(1))
    if existing_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Saved search name already exists.",
        )


async def _ensure_under_limit(db: AsyncSession, *, user_id: UUID) -> None:
    """Reject creating more saved searches than the per-user cap."""
    count = await db.scalar(
        select(func.count())
        .select_from(SavedSearch)
        .where(SavedSearch.user_id == user_id)
    )
    if (count or 0) >= MAX_SAVED_SEARCHES_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Saved search limit reached.",
        )


async def create_saved_search(
    *,
    db: AsyncSession,
    operator: User,
    payload: SavedSearchCreateRequest,
) -> SavedSearchResponse:
    """Create an Operator-owned saved Explore search."""
    user_id = operator.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        name = _normalise_name(payload.name)
        await _ensure_under_limit(db, user_id=user_id)
        await _ensure_name_available(db, user_id=user_id, name=name)
        saved_search = SavedSearch(
            user_id=user_id,
            name=name,
            filters=_normalise_filters(payload.filters),
            alert_enabled=payload.alert_enabled,
        )
        db.add(saved_search)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=user_id,
            action="saved_search_created",
            target_type="saved_search",
            target_id=saved_search.id,
            metadata={"alert_enabled": payload.alert_enabled},
        )
    await db.refresh(saved_search)
    logger.bind(
        module="saved_searches",
        action="create_saved_search",
        user_id=user_id,
        saved_search_id=saved_search.id,
    ).info("saved_search_created")
    return _to_response(saved_search)


async def list_saved_searches(
    *,
    db: AsyncSession,
    operator: User,
) -> SavedSearchListResponse:
    """Return saved searches owned by the authenticated Operator."""
    result = await db.execute(
        select(SavedSearch)
        .where(SavedSearch.user_id == operator.id)
        .order_by(desc(SavedSearch.created_at), SavedSearch.id.asc())
    )
    return SavedSearchListResponse(
        saved_searches=[_to_response(row) for row in result.scalars().all()]
    )


async def run_saved_search(
    *,
    db: AsyncSession,
    operator: User,
    saved_search_id: UUID,
    page: int,
    page_size: int,
) -> ExploreFrameworkListResponse:
    """Execute an owned saved search through the shared Explore query path."""
    saved_search = await _load_owned_saved_search(
        db,
        user_id=operator.id,
        saved_search_id=saved_search_id,
    )
    filters = ExploreSearchFilters.model_validate(saved_search.filters)
    return await explore_service.list_catalog_from_filters(
        db,
        current_user_id=operator.id,
        filters=filters,
        page=page,
        page_size=page_size,
    )


async def update_saved_search(
    *,
    db: AsyncSession,
    operator: User,
    saved_search_id: UUID,
    payload: SavedSearchUpdateRequest,
) -> SavedSearchResponse:
    """Edit an owned saved search name, filters, or alert toggle."""
    user_id = operator.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        saved_search = await _load_owned_saved_search(
            db,
            user_id=user_id,
            saved_search_id=saved_search_id,
        )
        fields = payload.model_fields_set
        if "name" in fields and payload.name is not None:
            name = _normalise_name(payload.name)
            await _ensure_name_available(
                db,
                user_id=user_id,
                name=name,
                excluding_id=saved_search.id,
            )
            saved_search.name = name
        if "filters" in fields and payload.filters is not None:
            saved_search.filters = _normalise_filters(payload.filters)
        if "alert_enabled" in fields and payload.alert_enabled is not None:
            saved_search.alert_enabled = payload.alert_enabled
        await write_audit(
            db=db,
            actor_id=user_id,
            action="saved_search_updated",
            target_type="saved_search",
            target_id=saved_search.id,
            metadata={"updated_fields": sorted(fields)},
        )
    await db.refresh(saved_search)
    logger.bind(
        module="saved_searches",
        action="update_saved_search",
        user_id=user_id,
        saved_search_id=saved_search.id,
    ).info("saved_search_updated")
    return _to_response(saved_search)


async def delete_saved_search(
    *,
    db: AsyncSession,
    operator: User,
    saved_search_id: UUID,
) -> None:
    """Delete an owned saved search and its future alert delivery state."""
    user_id = operator.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        saved_search = await _load_owned_saved_search(
            db,
            user_id=user_id,
            saved_search_id=saved_search_id,
        )
        await db.delete(saved_search)
        await write_audit(
            db=db,
            actor_id=user_id,
            action="saved_search_deleted",
            target_type="saved_search",
            target_id=saved_search.id,
            metadata={},
        )
    logger.bind(
        module="saved_searches",
        action="delete_saved_search",
        user_id=user_id,
        saved_search_id=saved_search_id,
    ).info("saved_search_deleted")
