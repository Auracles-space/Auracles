"""Service layer for contributor Collection CRUD and publishing.

Implements Phase 5b-1 Slice 2: owner-scoped collection lifecycle operations,
draft/unpublished member edits, publish-time bundle validation, and audit logs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.integrations import stripe
from app.integrations.stripe import StripeProviderError
from app.modules.auth.models import User
from app.modules.collections.models import (
    CollectionFramework,
    CollectionPurchaseSnapshot,
    FrameworkCollection,
)
from app.modules.collections.schemas import (
    CollectionCreateRequest,
    CollectionListResponse,
    CollectionMemberRequest,
    CollectionMemberResponse,
    CollectionResponse,
    CollectionUpdateRequest,
)
from app.modules.financials.models import Transaction
from app.modules.financials.schemas import PurchaseRequest, PurchaseResponse
from app.modules.frameworks.models import Framework, License

EDITABLE_COLLECTION_STATUSES = {"draft", "unpublished"}


def _normalise_money(amount: Decimal) -> Decimal:
    """Return a two-decimal money value for persisted collection purchases."""
    return amount.quantize(Decimal("0.01"))


def _masked_provider_ref(provider_ref: str) -> str:
    """Return a log-safe provider reference preserving only the final chars."""
    return f"****{provider_ref[-4:]}" if len(provider_ref) > 4 else "****"


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


async def _active_license_framework_ids(
    db: AsyncSession,
    *,
    operator_id: UUID,
    framework_ids: list[UUID],
) -> set[UUID]:
    """Return member Framework ids actively licensed by an Operator."""
    if not framework_ids:
        return set()
    now = datetime.now(UTC)
    rows = await db.execute(
        select(License.framework_id).where(
            License.operator_id == operator_id,
            License.framework_id.in_(framework_ids),
            License.status == "active",
            or_(License.expires_at.is_(None), License.expires_at > now),
        )
    )
    return set(rows.scalars().all())


async def _create_pending_collection_transaction(
    *,
    db: AsyncSession,
    operator_id: UUID,
    customer_id: str,
    collection_id: UUID,
    contributor_id: UUID,
    amount: Decimal,
    currency: str,
    member_snapshots: list[tuple[UUID, Decimal, bool]],
    license_type: str,
) -> UUID:
    """Persist a collection transaction and immutable member snapshot rows."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        operator_row = await db.get(User, operator_id)
        if operator_row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )
        if operator_row.stripe_customer_id is None:
            operator_row.stripe_customer_id = customer_id
        transaction = Transaction(
            payer_id=operator_id,
            payee_id=contributor_id,
            amount=_normalise_money(amount),
            currency=currency,
            platform_commission=Decimal("0.00"),
            net_amount=_normalise_money(amount),
            transaction_type="purchase",
            status="pending",
            provider="stripe",
            ref_id=collection_id,
            ref_type="collection",
        )
        db.add(transaction)
        await db.flush()
        for framework_id, list_price, already_owned in member_snapshots:
            db.add(
                CollectionPurchaseSnapshot(
                    transaction_id=transaction.id,
                    collection_id=collection_id,
                    framework_id=framework_id,
                    list_price_at_purchase=_normalise_money(list_price),
                    license_type=license_type,
                    already_owned=already_owned,
                )
            )
        await db.flush()
        return transaction.id


async def _mark_collection_purchase_initiated(
    *,
    db: AsyncSession,
    operator_id: UUID,
    transaction_id: UUID,
    provider_ref: str,
    collection_id: UUID,
    license_type: str,
    missing_member_count: int,
) -> None:
    """Attach provider metadata and audit collection checkout start."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        transaction = await db.get(Transaction, transaction_id)
        if transaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase transaction not found.",
            )
        transaction.provider_ref = provider_ref
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="collection_purchase_initiated",
            target_type="transaction",
            target_id=transaction.id,
            metadata={
                "provider": "stripe",
                "provider_ref": _masked_provider_ref(provider_ref),
                "collection_id": str(collection_id),
                "license_type": license_type,
                "missing_member_count": missing_member_count,
            },
        )


async def _mark_collection_purchase_failed(
    *,
    db: AsyncSession,
    operator_id: UUID,
    transaction_id: UUID,
    collection_id: UUID,
    license_type: str,
) -> None:
    """Mark a collection checkout transaction failed after provider failure."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        transaction = await db.get(Transaction, transaction_id)
        if transaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase transaction not found.",
            )
        transaction.status = "failed"
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="collection_purchase_failed",
            target_type="transaction",
            target_id=transaction.id,
            metadata={
                "provider": "stripe",
                "collection_id": str(collection_id),
                "license_type": license_type,
            },
        )


async def create_collection_purchase(
    *,
    db: AsyncSession,
    operator: User,
    collection_id: UUID,
    payload: PurchaseRequest,
) -> PurchaseResponse:
    """Create a pending Collection transaction and Stripe PaymentIntent."""
    operator_id = operator.id
    collection = await db.scalar(
        select(FrameworkCollection).where(
            FrameworkCollection.id == collection_id,
            FrameworkCollection.status == "published",
        )
    )
    if collection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found.",
        )
    if collection.contributor_id == operator_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot purchase your own Collection.",
        )

    collection_amount = _normalise_money(collection.bundle_price)
    collection_currency = collection.currency.upper()
    contributor_id = collection.contributor_id
    members = await _load_collection_members(db, collection.id)
    _validate_publishable(collection=collection, members=members)
    if collection_currency != "USD":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only USD collection purchases are supported.",
        )

    member_ids = [member.id for member in members]
    already_owned_ids = await _active_license_framework_ids(
        db,
        operator_id=operator_id,
        framework_ids=member_ids,
    )
    missing_members = [
        member for member in members if member.id not in already_owned_ids
    ]
    if not missing_members:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Collection is already fully licensed.",
        )
    if any(
        payload.license_type not in member.license_types for member in missing_members
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Selected license type is not available for every missing member.",
        )
    member_snapshots = [
        (member.id, member.price, member.id in already_owned_ids) for member in members
    ]

    customer_id = operator.stripe_customer_id
    try:
        if customer_id is None:
            customer = await stripe.create_customer(
                email=operator.email,
                name=operator.display_name,
                idempotency_key=f"stripe_customer:{operator_id}",
            )
            customer_id = customer.id
    except StripeProviderError as exc:
        logger.bind(
            module="collections",
            action="create_collection_purchase",
            user_id=operator_id,
            collection_id=collection_id,
        ).error("stripe_customer_create_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    transaction_id = await _create_pending_collection_transaction(
        db=db,
        operator_id=operator_id,
        customer_id=customer_id,
        collection_id=collection_id,
        contributor_id=contributor_id,
        amount=collection_amount,
        currency=collection_currency,
        member_snapshots=member_snapshots,
        license_type=payload.license_type,
    )
    try:
        payment_intent = await stripe.create_payment_intent(
            customer_id=customer_id,
            amount=collection_amount,
            currency=collection_currency,
            metadata={
                "kind": "collection",
                "transaction_id": str(transaction_id),
                "collection_id": str(collection_id),
            },
            idempotency_key=f"collection_purchase:{transaction_id}",
        )
    except StripeProviderError as exc:
        await _mark_collection_purchase_failed(
            db=db,
            operator_id=operator_id,
            transaction_id=transaction_id,
            collection_id=collection_id,
            license_type=payload.license_type,
        )
        logger.bind(
            module="collections",
            action="create_collection_purchase",
            user_id=operator_id,
            collection_id=collection_id,
            transaction_id=transaction_id,
        ).error("stripe_payment_intent_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    await _mark_collection_purchase_initiated(
        db=db,
        operator_id=operator_id,
        transaction_id=transaction_id,
        provider_ref=payment_intent.id,
        collection_id=collection_id,
        license_type=payload.license_type,
        missing_member_count=len(missing_members),
    )
    logger.bind(
        module="collections",
        action="create_collection_purchase",
        user_id=operator_id,
        collection_id=collection_id,
        transaction_id=transaction_id,
    ).info("collection_purchase_initiated")
    return PurchaseResponse(
        transaction_id=transaction_id,
        provider="stripe",
        client_secret=payment_intent.client_secret,
    )


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
