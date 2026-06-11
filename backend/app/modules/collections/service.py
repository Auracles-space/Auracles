"""Service layer for contributor Collection CRUD and publishing.

Implements Phase 5b-1 Slice 2: owner-scoped collection lifecycle operations,
draft/unpublished member edits, publish-time bundle validation, and audit logs.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.auth.models import User
from app.modules.collections.models import CollectionFramework, FrameworkCollection
from app.modules.collections.schemas import (
    CollectionCreateRequest,
    CollectionListResponse,
    CollectionMemberRequest,
    CollectionMemberResponse,
    CollectionResponse,
    CollectionUpdateRequest,
)
from app.modules.frameworks.models import Framework

EDITABLE_COLLECTION_STATUSES = {"draft", "unpublished"}


async def _load_owned_collection(
    db: AsyncSession,
    *,
    contributor_id: UUID,
    collection_id: UUID,
) -> FrameworkCollection:
    """Load an owned Collection or raise 404."""
    collection = await db.scalar(
        select(FrameworkCollection).where(
            FrameworkCollection.id == collection_id,
            FrameworkCollection.contributor_id == contributor_id,
        )
    )
    if collection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found.",
        )
    return collection


def _require_editable(collection: FrameworkCollection) -> None:
    """Reject member or metadata edits while a Collection is published."""
    if collection.status not in EDITABLE_COLLECTION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Published Collections must be unpublished before editing.",
        )


async def _load_collection_members(
    db: AsyncSession,
    collection_id: UUID,
) -> list[Framework]:
    """Return member Frameworks in deterministic title order."""
    result = await db.execute(
        select(Framework)
        .join(CollectionFramework, CollectionFramework.framework_id == Framework.id)
        .where(CollectionFramework.collection_id == collection_id)
        .order_by(Framework.title.asc(), Framework.id.asc())
    )
    return list(result.scalars().all())


def _member_to_response(framework: Framework) -> CollectionMemberResponse:
    """Map a Framework row to the embedded Collection member summary."""
    return CollectionMemberResponse(
        framework_id=framework.id,
        title=framework.title,
        status=framework.status,
        price=framework.price,
        currency=framework.currency,
    )


async def collection_to_response(
    db: AsyncSession,
    collection: FrameworkCollection,
) -> CollectionResponse:
    """Map a Collection row and its current members to an API response."""
    members = await _load_collection_members(db, collection.id)
    return CollectionResponse(
        id=collection.id,
        contributor_id=collection.contributor_id,
        title=collection.title,
        description=collection.description,
        bundle_price=collection.bundle_price,
        currency=collection.currency,
        status=collection.status,
        members=[_member_to_response(member) for member in members],
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


async def create_collection(
    *,
    db: AsyncSession,
    contributor: User,
    payload: CollectionCreateRequest,
) -> CollectionResponse:
    """Create a draft Collection for the authenticated Contributor."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        collection = FrameworkCollection(
            contributor_id=contributor_id,
            title=payload.title.strip(),
            description=payload.description.strip(),
            bundle_price=payload.bundle_price,
            currency=payload.currency,
        )
        db.add(collection)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="collection_created",
            target_type="collection",
            target_id=collection.id,
            metadata={"status": collection.status},
        )
    await db.refresh(collection)
    logger.bind(
        module="collections",
        action="create_collection",
        user_id=contributor_id,
        collection_id=collection.id,
    ).info("collection_created")
    return await collection_to_response(db, collection)


async def list_my_collections(
    *,
    db: AsyncSession,
    contributor: User,
) -> CollectionListResponse:
    """Return Collections owned by the authenticated Contributor."""
    result = await db.execute(
        select(FrameworkCollection)
        .where(FrameworkCollection.contributor_id == contributor.id)
        .order_by(desc(FrameworkCollection.created_at))
    )
    collections = list(result.scalars().all())
    return CollectionListResponse(
        collections=[
            await collection_to_response(db, collection) for collection in collections
        ]
    )


async def get_collection(
    *,
    db: AsyncSession,
    contributor: User,
    collection_id: UUID,
) -> CollectionResponse:
    """Return one Collection owned by the authenticated Contributor."""
    collection = await _load_owned_collection(
        db,
        contributor_id=contributor.id,
        collection_id=collection_id,
    )
    return await collection_to_response(db, collection)


async def update_collection(
    *,
    db: AsyncSession,
    contributor: User,
    collection_id: UUID,
    payload: CollectionUpdateRequest,
) -> CollectionResponse:
    """Edit metadata or price for an unpublished Collection."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        collection = await _load_owned_collection(
            db,
            contributor_id=contributor_id,
            collection_id=collection_id,
        )
        _require_editable(collection)
        fields = payload.model_fields_set
        if "title" in fields and payload.title is not None:
            collection.title = payload.title.strip()
        if "description" in fields and payload.description is not None:
            collection.description = payload.description.strip()
        if "bundle_price" in fields and payload.bundle_price is not None:
            collection.bundle_price = payload.bundle_price
        if "currency" in fields and payload.currency is not None:
            collection.currency = payload.currency
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="collection_updated",
            target_type="collection",
            target_id=collection.id,
            metadata={"status": collection.status},
        )
    await db.refresh(collection)
    logger.bind(
        module="collections",
        action="update_collection",
        user_id=contributor_id,
        collection_id=collection.id,
    ).info("collection_updated")
    return await collection_to_response(db, collection)


async def add_collection_member(
    *,
    db: AsyncSession,
    contributor: User,
    collection_id: UUID,
    payload: CollectionMemberRequest,
) -> CollectionResponse:
    """Add one owned Framework to an editable Collection."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        collection = await _load_owned_collection(
            db,
            contributor_id=contributor_id,
            collection_id=collection_id,
        )
        _require_editable(collection)
        framework = await db.scalar(
            select(Framework).where(Framework.id == payload.framework_id)
        )
        if framework is None or framework.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )
        if framework.contributor_id != contributor_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Collection members must belong to the same Contributor.",
            )
        existing = await db.scalar(
            select(CollectionFramework).where(
                CollectionFramework.collection_id == collection.id,
                CollectionFramework.framework_id == framework.id,
            )
        )
        if existing is None:
            db.add(
                CollectionFramework(
                    collection_id=collection.id,
                    framework_id=framework.id,
                )
            )
            await db.flush()
            await write_audit(
                db=db,
                actor_id=contributor_id,
                action="collection_member_added",
                target_type="collection",
                target_id=collection.id,
                metadata={"framework_id": str(framework.id)},
            )
    await db.refresh(collection)
    logger.bind(
        module="collections",
        action="add_collection_member",
        user_id=contributor_id,
        collection_id=collection.id,
        framework_id=payload.framework_id,
    ).info("collection_member_added")
    return await collection_to_response(db, collection)


async def remove_collection_member(
    *,
    db: AsyncSession,
    contributor: User,
    collection_id: UUID,
    framework_id: UUID,
) -> CollectionResponse:
    """Remove one Framework from an editable Collection."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        collection = await _load_owned_collection(
            db,
            contributor_id=contributor_id,
            collection_id=collection_id,
        )
        _require_editable(collection)
        member = await db.scalar(
            select(CollectionFramework).where(
                CollectionFramework.collection_id == collection.id,
                CollectionFramework.framework_id == framework_id,
            )
        )
        if member is not None:
            await db.delete(member)
            await write_audit(
                db=db,
                actor_id=contributor_id,
                action="collection_member_removed",
                target_type="collection",
                target_id=collection.id,
                metadata={"framework_id": str(framework_id)},
            )
    await db.refresh(collection)
    logger.bind(
        module="collections",
        action="remove_collection_member",
        user_id=contributor_id,
        collection_id=collection.id,
        framework_id=framework_id,
    ).info("collection_member_removed")
    return await collection_to_response(db, collection)


def _validate_publishable(
    *,
    collection: FrameworkCollection,
    members: list[Framework],
) -> Decimal:
    """Validate BR-COL-001..003 and return the member price sum."""
    if len(members) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Collection must include at least two member Frameworks.",
        )
    for member in members:
        if member.contributor_id != collection.contributor_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Collection members must belong to the same Contributor.",
            )
        if member.status != "published" or member.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Collection members must all be published Frameworks.",
            )
    member_price_sum = sum((member.price for member in members), Decimal("0.00"))
    if collection.bundle_price >= member_price_sum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Collection bundle_price must be lower than member price sum.",
        )
    return member_price_sum


async def publish_collection(
    *,
    db: AsyncSession,
    contributor: User,
    collection_id: UUID,
) -> CollectionResponse:
    """Publish an owned Collection after validating its member bundle rules."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        collection = await _load_owned_collection(
            db,
            contributor_id=contributor_id,
            collection_id=collection_id,
        )
        if collection.status == "published":
            return await collection_to_response(db, collection)
        members = await _load_collection_members(db, collection.id)
        member_price_sum = _validate_publishable(
            collection=collection,
            members=members,
        )
        collection.status = "published"
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="collection_published",
            target_type="collection",
            target_id=collection.id,
            metadata={
                "member_count": len(members),
                "member_price_sum": f"{member_price_sum:.2f}",
            },
        )
    await db.refresh(collection)
    logger.bind(
        module="collections",
        action="publish_collection",
        user_id=contributor_id,
        collection_id=collection.id,
    ).info("collection_published")
    return await collection_to_response(db, collection)


async def unpublish_collection(
    *,
    db: AsyncSession,
    contributor: User,
    collection_id: UUID,
) -> CollectionResponse:
    """Move an owned Collection out of Explore without touching buyer licenses."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        collection = await _load_owned_collection(
            db,
            contributor_id=contributor_id,
            collection_id=collection_id,
        )
        if collection.status == "unpublished":
            return await collection_to_response(db, collection)
        if collection.status != "published":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only published Collections can be unpublished.",
            )
        collection.status = "unpublished"
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="collection_unpublished",
            target_type="collection",
            target_id=collection.id,
            metadata={},
        )
    await db.refresh(collection)
    logger.bind(
        module="collections",
        action="unpublish_collection",
        user_id=contributor_id,
        collection_id=collection.id,
    ).info("collection_unpublished")
    return await collection_to_response(db, collection)
