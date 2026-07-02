"""Sticky Certified Attestor evaluation.

Module 6b awards Certified Attestor status when an attestor crosses the merit
threshold for stood-attestation volume and average rating. The award is sticky:
once ``certified_attestor_at`` is set, recompute never clears or re-stamps it.

Maps to: Module 6b design spec section 4.3.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.attestation.models import (
    Attestation,
    AttestationRating,
    AttestorProfile,
)
from app.modules.reputation.weights import ReputationConfig


async def evaluate_attestor_certification(
    db: AsyncSession,
    *,
    attestor_id: UUID,
    cfg: ReputationConfig,
) -> bool:
    """Award Certified Attestor status when merit thresholds are first met.

    Runs inside the caller's transaction. The attestor profile is locked so the
    sticky certification timestamp and audit write stay idempotent across
    concurrent or retried recomputes.

    Args:
        db: Async SQLAlchemy session with an open transaction.
        attestor_id: User id of the attestor being evaluated.
        cfg: Loaded attestor reputation config supplying certification thresholds.

    Returns:
        ``True`` when this call newly certifies the attestor, else ``False``.
    """
    profile = await db.scalar(
        select(AttestorProfile)
        .where(AttestorProfile.user_id == attestor_id)
        .with_for_update()
    )
    if profile is None or profile.certified_attestor_at is not None:
        return False

    stood_attestations = (
        select(Attestation.id)
        .where(
            Attestation.attestor_id == attestor_id,
            Attestation.status == "closed",
            Attestation.report_published_eligible.is_(True),
        )
        .subquery()
    )
    stood_count = int(
        await db.scalar(select(func.count()).select_from(stood_attestations)) or 0
    )
    if stood_count < cfg.cert_min_attestations:
        return False

    avg_stars = await db.scalar(
        select(func.avg(AttestationRating.stars)).where(
            AttestationRating.attestation_id.in_(select(stood_attestations.c.id))
        )
    )
    if avg_stars is None or Decimal(str(avg_stars)) < cfg.cert_min_avg_rating:
        return False

    profile.certified_attestor_at = datetime.now(UTC)
    await write_audit(
        db=db,
        actor_id=None,
        action="attestor_certified",
        target_type="attestor",
        target_id=attestor_id,
        metadata={
            "stood_count": stood_count,
            "avg_rating": str(avg_stars),
        },
    )
    logger.bind(
        module="attestation",
        action="attestor_certified",
        user_id=attestor_id,
    ).info("attestor_certified", stood_count=stood_count)
    return True
