"""Partner commission lifecycle services.

Handles Phase 5a commission state transitions that are shared by webhook,
scheduled clearing, analytics, and future payout slices.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.developer.models import DeveloperAccount, PartnerCommission
from app.modules.developer.schemas import (
    DeveloperTierProgressResponse,
    PartnerTierResponse,
)
from app.modules.financials.models import PlatformConfig, Transaction

COMMISSION_CLEARING_DELAY = timedelta(hours=48)
TIER_RECOMPUTE_WINDOW = timedelta(days=30)
DEFAULT_PARTNER_TIER_THRESHOLDS = {
    "1": {"min": 0, "max": 99, "rate": "0.0500"},
    "2": {"min": 100, "max": 499, "rate": "0.0800"},
    "3": {"min": 500, "max": None, "rate": "0.1200"},
}


@dataclass(frozen=True)
class PartnerTier:
    """Validated Partner commission tier configuration."""

    tier: int
    min_sales: int
    max_sales: int | None
    rate: Decimal


async def clear_partner_commissions(db: AsyncSession) -> dict[str, int]:
    """Clear mature Partner commissions and void refunded-sale commissions.

    Pending commissions become `cleared` only after the 48-hour refund window
    has elapsed and the linked purchase transaction is still completed. Pending
    commissions tied to refunded transactions are voided so they cannot be paid.
    """
    now = datetime.now(UTC)
    cutoff = now - COMMISSION_CLEARING_DELAY
    cleared_count = 0
    voided_count = 0

    rows = (
        await db.execute(
            select(PartnerCommission, Transaction)
            .join(Transaction, Transaction.id == PartnerCommission.transaction_id)
            .where(PartnerCommission.status == "pending")
            .with_for_update()
        )
    ).all()

    for commission, transaction in rows:
        if transaction.status == "refunded":
            commission.status = "voided"
            voided_count += 1
            await write_audit(
                db=db,
                actor_id=None,
                action="partner_commission_voided",
                target_type="partner_commission",
                target_id=commission.id,
                metadata={
                    "transaction_id": str(transaction.id),
                    "reason": "refund_detected_by_clearing_task",
                },
            )
            continue

        if transaction.status == "completed" and commission.created_at <= cutoff:
            commission.status = "cleared"
            commission.cleared_at = now
            cleared_count += 1
            await write_audit(
                db=db,
                actor_id=None,
                action="partner_commission_cleared",
                target_type="partner_commission",
                target_id=commission.id,
                metadata={
                    "transaction_id": str(transaction.id),
                    "cleared_after_hours": 48,
                },
            )

    return {"cleared_count": cleared_count, "voided_count": voided_count}


def _normalise_rate(rate: Decimal) -> Decimal:
    """Return a four-decimal commission rate."""
    return rate.quantize(Decimal("0.0001"))


def _parse_decimal(value: object, *, field_name: str) -> Decimal:
    """Parse a decimal tier config field."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{field_name} in partner_tier_thresholds is invalid.",
        ) from exc


def _parse_int(value: object, *, field_name: str) -> int:
    """Parse an integer tier config field."""
    try:
        parsed = int(str(value))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{field_name} in partner_tier_thresholds is invalid.",
        ) from exc
    if parsed < 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{field_name} in partner_tier_thresholds cannot be negative.",
        )
    return parsed


async def _platform_commission_rate(db: AsyncSession) -> Decimal:
    """Return platform commission rate for partner tier validation."""
    configured = await db.scalar(
        select(PlatformConfig.value).where(PlatformConfig.key == "commission_rate")
    )
    if configured is None:
        return Decimal("0.15")
    try:
        return Decimal(configured)
    except InvalidOperation as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commission_rate configuration is invalid.",
        ) from exc


async def load_partner_tiers(db: AsyncSession) -> list[PartnerTier]:
    """Load and validate Partner tier thresholds from platform config."""
    raw_config = await db.scalar(
        select(PlatformConfig.value).where(
            PlatformConfig.key == "partner_tier_thresholds"
        )
    )
    try:
        config = (
            json.loads(raw_config) if raw_config else DEFAULT_PARTNER_TIER_THRESHOLDS
        )
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="partner_tier_thresholds configuration is invalid JSON.",
        ) from exc

    if not isinstance(config, dict) or set(config) != {"1", "2", "3"}:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="partner_tier_thresholds must define tiers 1, 2, and 3.",
        )

    commission_rate = await _platform_commission_rate(db)
    tiers: list[PartnerTier] = []
    for tier_key in ("1", "2", "3"):
        value = config[tier_key]
        if not isinstance(value, dict):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="partner_tier_thresholds tier entries must be objects.",
            )
        min_sales = _parse_int(value.get("min"), field_name=f"tier {tier_key} min")
        max_value = value.get("max")
        max_sales = (
            None
            if max_value is None
            else _parse_int(max_value, field_name=f"tier {tier_key} max")
        )
        if max_sales is not None and max_sales < min_sales:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="partner_tier_thresholds max cannot be below min.",
            )
        rate = _normalise_rate(
            _parse_decimal(value.get("rate"), field_name=f"tier {tier_key} rate")
        )
        if rate < 0 or rate > commission_rate:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="partner tier rates must fit inside platform commission.",
            )
        tiers.append(
            PartnerTier(
                tier=int(tier_key),
                min_sales=min_sales,
                max_sales=max_sales,
                rate=rate,
            )
        )

    sorted_tiers = sorted(tiers, key=lambda item: item.min_sales)
    previous_max: int | None = None
    for tier in sorted_tiers:
        if previous_max is not None and tier.min_sales <= previous_max:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="partner_tier_thresholds ranges cannot overlap.",
            )
        previous_max = tier.max_sales
    return tiers


def tier_for_sales_count(tiers: list[PartnerTier], sales_count: int) -> PartnerTier:
    """Return the configured tier for a prior-30-day sales count."""
    sorted_tiers = sorted(tiers, key=lambda item: item.min_sales)
    for tier in sorted_tiers:
        if sales_count >= tier.min_sales and (
            tier.max_sales is None or sales_count <= tier.max_sales
        ):
            return tier
    return sorted_tiers[0]


async def partner_sales_count(
    db: AsyncSession,
    *,
    developer_account_id: UUID,
    since: datetime | None = None,
) -> int:
    """Count non-voided Partner sales for one Developer account."""
    filters = [
        PartnerCommission.developer_account_id == developer_account_id,
        PartnerCommission.status != "voided",
    ]
    if since is not None:
        filters.append(PartnerCommission.created_at >= since)
    value = await db.scalar(
        select(func.count(PartnerCommission.id)).where(*filters)
    )
    return int(value or 0)


async def recompute_partner_tiers(db: AsyncSession) -> dict[str, int]:
    """Recompute Developer commission tiers from prior-30-day sales counts."""
    now = datetime.now(UTC)
    cutoff = now - TIER_RECOMPUTE_WINDOW
    tiers = await load_partner_tiers(db)
    processed_count = 0
    updated_count = 0
    accounts = (
        await db.execute(
            select(DeveloperAccount)
            .where(DeveloperAccount.status == "active")
            .with_for_update()
        )
    ).scalars().all()

    for account in accounts:
        processed_count += 1
        sales_count = await partner_sales_count(
            db,
            developer_account_id=account.id,
            since=cutoff,
        )
        tier = tier_for_sales_count(tiers, sales_count)
        changed = (
            account.commission_tier != tier.tier
            or _normalise_rate(account.tier_rate) != tier.rate
            or account.tier_sales_count != sales_count
        )
        if not changed:
            continue

        old_tier = account.commission_tier
        old_rate = _normalise_rate(account.tier_rate)
        account.commission_tier = tier.tier
        account.tier_rate = tier.rate
        account.tier_sales_count = sales_count
        account.tier_recalculated_at = now
        updated_count += 1
        await write_audit(
            db=db,
            actor_id=None,
            action="partner_tier_recomputed",
            target_type="developer_account",
            target_id=account.id,
            metadata={
                "old_tier": old_tier,
                "new_tier": tier.tier,
                "old_rate": str(old_rate),
                "new_rate": str(tier.rate),
                "prior_30d_sales_count": sales_count,
            },
        )

    return {"processed_count": processed_count, "updated_count": updated_count}


async def get_tier_progress(
    db: AsyncSession,
    *,
    developer_account: DeveloperAccount,
) -> DeveloperTierProgressResponse:
    """Return current tier and next-tier progress for one Developer account."""
    tiers = await load_partner_tiers(db)
    live_sales_count = await partner_sales_count(
        db,
        developer_account_id=developer_account.id,
        since=datetime.now(UTC) - TIER_RECOMPUTE_WINDOW,
    )
    sorted_tiers = sorted(tiers, key=lambda item: item.tier)
    next_tier = next(
        (
            tier
            for tier in sorted_tiers
            if tier.tier > developer_account.commission_tier
        ),
        None,
    )
    return DeveloperTierProgressResponse(
        current_tier=developer_account.commission_tier,
        current_rate=_normalise_rate(developer_account.tier_rate),
        prior_30d_sales_count=live_sales_count,
        next_tier=next_tier.tier if next_tier is not None else None,
        next_tier_sales_required=(
            max(next_tier.min_sales - live_sales_count, 0)
            if next_tier is not None
            else None
        ),
        tier_recalculated_at=developer_account.tier_recalculated_at,
        tiers=[
            PartnerTierResponse(
                tier=tier.tier,
                min_sales=tier.min_sales,
                max_sales=tier.max_sales,
                rate=tier.rate,
            )
            for tier in sorted_tiers
        ],
    )
