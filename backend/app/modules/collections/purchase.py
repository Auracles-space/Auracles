"""Collection purchase confirmation helpers.

Stripe webhook handlers call this module after a Collection PaymentIntent
succeeds. The checkout snapshot, not current collection membership, is the
source of truth for minted Licenses and earning allocations.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.collections.models import (
    CollectionEarningAllocation,
    CollectionPurchaseSnapshot,
)
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework, License


class CollectionPurchaseProcessingError(RuntimeError):
    """Raised when a Collection purchase webhook cannot be safely completed."""


def _normalise_money(amount: Decimal) -> Decimal:
    """Return a two-decimal money value for allocation rows."""
    return amount.quantize(Decimal("0.01"))


def _license_seats_total(license_type: str) -> int | None:
    """Return default seat allocation for purchased Collection member licenses."""
    if license_type == "single_user":
        return 1
    if license_type == "team":
        return 10
    return None


def _allocation_amounts(
    *,
    total_amount: Decimal,
    minted_snapshots: list[CollectionPurchaseSnapshot],
) -> dict[UUID, Decimal]:
    """Allocate bundle revenue across minted members using list-price ratios."""
    if not minted_snapshots:
        return {}
    total_list_price = sum(
        (snapshot.list_price_at_purchase for snapshot in minted_snapshots),
        Decimal("0.00"),
    )
    if total_list_price <= 0:
        raise CollectionPurchaseProcessingError("collection snapshot prices invalid")

    allocations: dict[UUID, Decimal] = {}
    running_total = Decimal("0.00")
    highest_price_snapshot = max(
        minted_snapshots,
        key=lambda snapshot: (
            snapshot.list_price_at_purchase,
            str(snapshot.framework_id),
        ),
    )
    for snapshot in minted_snapshots:
        raw_amount = total_amount * snapshot.list_price_at_purchase / total_list_price
        amount = raw_amount.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        allocations[snapshot.framework_id] = amount
        running_total += amount

    remainder = _normalise_money(total_amount - running_total)
    allocations[highest_price_snapshot.framework_id] = _normalise_money(
        allocations[highest_price_snapshot.framework_id] + remainder
    )
    return allocations


async def _load_snapshot_frameworks(
    db: AsyncSession,
    snapshots: list[CollectionPurchaseSnapshot],
) -> dict[UUID, Framework]:
    """Load all snapshotted Framework rows keyed by id."""
    framework_ids = [snapshot.framework_id for snapshot in snapshots]
    rows = await db.execute(select(Framework).where(Framework.id.in_(framework_ids)))
    return {framework.id: framework for framework in rows.scalars().all()}


async def confirm_collection_purchase(
    db: AsyncSession,
    *,
    transaction_id: UUID,
    payment_intent_id: str | None,
) -> UUID:
    """Complete a Collection purchase from its checkout snapshot.

    Args:
        db: Async SQLAlchemy session inside the webhook transaction boundary.
        transaction_id: Pending collection purchase transaction id.
        payment_intent_id: Stripe PaymentIntent id from the verified event.

    Returns:
        The completed transaction id for invoice generation.

    Raises:
        CollectionPurchaseProcessingError: If local purchase state is invalid.
    """
    transaction = await db.scalar(
        select(Transaction).where(Transaction.id == transaction_id).with_for_update()
    )
    if transaction is None:
        raise CollectionPurchaseProcessingError("collection transaction not found")
    if (
        transaction.transaction_type != "purchase"
        or transaction.ref_type != "collection"
    ):
        raise CollectionPurchaseProcessingError(
            "transaction is not a collection purchase"
        )
    if transaction.provider != "stripe":
        raise CollectionPurchaseProcessingError("transaction provider mismatch")
    if transaction.provider_ref and transaction.provider_ref != payment_intent_id:
        raise CollectionPurchaseProcessingError("payment intent id mismatch")
    if transaction.ref_id is None:
        raise CollectionPurchaseProcessingError("collection transaction missing ref")

    snapshots = list(
        (
            await db.execute(
                select(CollectionPurchaseSnapshot)
                .where(CollectionPurchaseSnapshot.transaction_id == transaction.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if not snapshots:
        raise CollectionPurchaseProcessingError("collection snapshots not found")

    frameworks = await _load_snapshot_frameworks(db, snapshots)
    for snapshot in snapshots:
        framework = frameworks.get(snapshot.framework_id)
        if framework is None or framework.deleted_at is not None:
            await write_audit(
                db=db,
                actor_id=transaction.payer_id,
                action="collection_purchase_needs_refund",
                target_type="transaction",
                target_id=transaction.id,
                metadata={
                    "collection_id": str(transaction.ref_id),
                    "framework_id": str(snapshot.framework_id),
                    "reason": "framework_missing",
                },
            )
            raise CollectionPurchaseProcessingError("collection framework missing")
        if framework.status != "published":
            await write_audit(
                db=db,
                actor_id=transaction.payer_id,
                action="collection_purchase_needs_refund",
                target_type="transaction",
                target_id=transaction.id,
                metadata={
                    "collection_id": str(transaction.ref_id),
                    "framework_id": str(snapshot.framework_id),
                    "reason": "framework_not_published",
                },
            )
            raise CollectionPurchaseProcessingError("collection framework unavailable")

    minted_snapshots: list[CollectionPurchaseSnapshot] = []
    minted_license_ids: list[str] = []
    midflight_owned_framework_ids: list[str] = []
    for snapshot in snapshots:
        if snapshot.already_owned:
            continue
        framework = frameworks[snapshot.framework_id]
        existing_license = await db.scalar(
            select(License)
            .where(
                License.framework_id == snapshot.framework_id,
                License.operator_id == transaction.payer_id,
            )
            .with_for_update()
        )
        if existing_license is None:
            existing_license = License(
                framework_id=snapshot.framework_id,
                operator_id=transaction.payer_id,
                transaction_id=transaction.id,
                source="collection",
                collection_id=transaction.ref_id,
                license_type=snapshot.license_type,
                status="active",
                version_at_grant=framework.version,
                seats_used=1,
                seats_total=_license_seats_total(snapshot.license_type),
            )
            db.add(existing_license)
            await db.flush()
            minted_snapshots.append(snapshot)
            minted_license_ids.append(str(existing_license.id))
            continue
        if existing_license.transaction_id == transaction.id:
            minted_snapshots.append(snapshot)
            minted_license_ids.append(str(existing_license.id))
            continue
        if existing_license.status == "active":
            midflight_owned_framework_ids.append(str(snapshot.framework_id))
            continue
        if existing_license.status != "active":
            existing_license.transaction_id = transaction.id
            existing_license.source = "collection"
            existing_license.collection_id = transaction.ref_id
            existing_license.license_type = snapshot.license_type
            existing_license.status = "active"
            existing_license.version_at_grant = framework.version
            existing_license.seats_used = 1
            existing_license.seats_total = _license_seats_total(snapshot.license_type)
            minted_snapshots.append(snapshot)
            minted_license_ids.append(str(existing_license.id))

    if midflight_owned_framework_ids:
        await write_audit(
            db=db,
            actor_id=transaction.payer_id,
            action="collection_purchase_needs_refund",
            target_type="transaction",
            target_id=transaction.id,
            metadata={
                "collection_id": str(transaction.ref_id),
                "framework_ids": midflight_owned_framework_ids,
                "reason": "license_already_active",
            },
        )
        raise CollectionPurchaseProcessingError("collection member already licensed")

    existing_allocation_id = await db.scalar(
        select(CollectionEarningAllocation.id)
        .where(CollectionEarningAllocation.transaction_id == transaction.id)
        .limit(1)
    )
    if existing_allocation_id is None:
        allocations = _allocation_amounts(
            total_amount=_normalise_money(transaction.amount),
            minted_snapshots=minted_snapshots,
        )
        for framework_id, allocated_amount in allocations.items():
            db.add(
                CollectionEarningAllocation(
                    transaction_id=transaction.id,
                    collection_id=transaction.ref_id,
                    framework_id=framework_id,
                    allocated_amount=allocated_amount,
                )
            )

    transaction.status = "completed"
    await write_audit(
        db=db,
        actor_id=transaction.payer_id,
        action="collection_purchased",
        target_type="transaction",
        target_id=transaction.id,
        metadata={
            "provider": "stripe",
            "collection_id": str(transaction.ref_id),
            "minted_license_count": len(minted_license_ids),
            "license_ids": minted_license_ids,
        },
    )
    return transaction.id
