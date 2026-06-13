"""Reputation compute engine + persistence + reads.

Combines per-subject factor results into a 0-100 score with shrinkage toward a
neutral prior, provisional gating for low-evidence subjects, and an upsert into
``reputation_scores``. See the Phase 5e design spec.

Maps to: BR-ATT-005, BR-FWK-005.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reputation.models import ReputationScore
from app.modules.reputation.weights import ReputationConfig

_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")


@dataclass(frozen=True)
class FactorResult:
    """One normalized factor contribution and its supporting evidence count."""

    value: Decimal  # normalized 0..1
    evidence: int  # evidence count contributing to this factor


@dataclass(frozen=True)
class ScoreResult:
    """Combined reputation outcome for one subject."""

    score: Decimal  # 0..100, two decimals
    components: dict[str, Any]
    is_provisional: bool
    evidence: int


def _clamp(value: Decimal) -> Decimal:
    """Clamp a normalized value into the closed unit interval."""
    return min(Decimal("1"), max(Decimal("0"), value))


def _label(value: Decimal) -> str:
    """Map a normalized value to a public strength label."""
    if value >= Decimal("0.66"):
        return "strong"
    if value >= Decimal("0.33"):
        return "moderate"
    return "weak"


def _component(fr: FactorResult) -> dict[str, str]:
    """Render one factor's public component payload (clamped value + label)."""
    clamped = _clamp(fr.value)
    return {"value": str(clamped.quantize(_FOUR)), "label": _label(clamped)}


def combine_factors(
    cfg: ReputationConfig,
    factors: dict[str, FactorResult],
) -> ScoreResult:
    """Weight, shrink toward prior, and label factor results into a ScoreResult.

    Args:
        cfg: Loaded reputation config for the subject type (weights, prior, k,
            min-activity threshold).
        factors: Mapping of factor name to its normalized result.

    Returns:
        A ScoreResult with a 0-100 score, public component labels, the
        provisional flag, and total evidence volume.
    """
    raw = Decimal("0")
    for name, weight in cfg.weights.items():
        fr = factors.get(name, FactorResult(Decimal("0"), 0))
        raw += weight * _clamp(fr.value)

    total_evidence = sum(fr.evidence for fr in factors.values())
    n = Decimal(total_evidence)
    k = cfg.prior_strength_k
    denom = n + k
    # denom == 0 only when both evidence and prior strength are zero.
    shrunk = raw if denom == 0 else (n / denom) * raw + (k / denom) * cfg.prior
    score = (shrunk * Decimal("100")).quantize(_TWO, rounding=ROUND_HALF_UP)

    components = {
        name: _component(factors.get(name, FactorResult(Decimal("0"), 0)))
        for name in cfg.weights
    }
    is_provisional = total_evidence < cfg.min_activity
    return ScoreResult(score, components, is_provisional, total_evidence)


async def upsert_score(
    db: AsyncSession,
    *,
    subject_type: str,
    subject_id: UUID,
    result: ScoreResult,
) -> None:
    """Idempotently upsert one computed score row."""
    now = datetime.now(UTC)
    stmt = (
        pg_insert(ReputationScore)
        .values(
            subject_type=subject_type,
            subject_id=subject_id,
            score=result.score,
            components=result.components,
            is_provisional=result.is_provisional,
            last_calculated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_reputation_subject",
            set_={
                "score": result.score,
                "components": result.components,
                "is_provisional": result.is_provisional,
                "last_calculated_at": now,
                "updated_at": now,
            },
        )
    )
    await db.execute(stmt)


async def get_score(
    db: AsyncSession,
    *,
    subject_type: str,
    subject_id: UUID,
) -> ReputationScore | None:
    """Return the latest stored reputation score for one subject, if any."""
    return await db.scalar(
        select(ReputationScore).where(
            ReputationScore.subject_type == subject_type,
            ReputationScore.subject_id == subject_id,
        )
    )
