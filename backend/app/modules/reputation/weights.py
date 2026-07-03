"""Reputation configuration loading and validation helpers.

This module reads reputation weighting and threshold values from
``platform_config`` and supplies safe defaults when overrides are absent.
Phase 5e scoring code depends on this module rather than reading raw config
rows directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.financials.models import PlatformConfig

_DEFAULT_WEIGHTS: dict[str, dict[str, str]] = {
    "framework": {
        "reviews": "0.35",
        "attestations": "0.30",
        "adoption": "0.35",
        "completion": "0.00",
        "recency": "0.00",
    },
    "contributor": {
        "verification": "0.15",
        "framework_performance": "0.30",
        "reviews_received": "0.20",
        "attestations_received": "0.20",
        "activity": "0.15",
    },
    "operator": {
        "purchase_activity": "0.40",
        "license_compliance": "0.25",
        "review_quality": "0.20",
        "engagement": "0.15",
    },
    "attestor": {
        "rating": "0.75",
        "reliability": "0.25",
    },
}
_DEFAULT_MIN_ACTIVITY = {
    "framework": 3,
    "contributor": 1,
    "operator": 1,
    "attestor": 3,
}


@dataclass(frozen=True)
class ReputationConfig:
    """Normalized reputation config for one subject type."""

    subject_type: str
    weights: dict[str, Decimal]
    min_activity: int
    prior: Decimal
    prior_strength_k: Decimal
    decay_halflife_days: int
    dispute_penalty: Decimal
    reliability_penalty: Decimal = Decimal("0.10")
    cert_min_attestations: int = 10
    cert_min_avg_rating: Decimal = Decimal("4.5")


def validate_weight_map(weights_map: dict[str, Decimal], *, subject_type: str) -> None:
    """Validate that a weight map matches the expected factors and sums to one."""
    expected = set(expected_weight_keys(subject_type))
    actual = set(weights_map)
    if actual != expected:
        raise ValueError(
            f"reputation weights for {subject_type} must use keys {sorted(expected)}"
        )
    if any(weight < 0 for weight in weights_map.values()):
        raise ValueError("reputation weights must be non-negative")

    total = sum(weights_map.values())
    if abs(total - Decimal("1")) > Decimal("0.001"):
        raise ValueError(f"reputation weights must sum to 1.0 (got {total})")


def expected_weight_keys(subject_type: str) -> tuple[str, ...]:
    """Return the supported factor keys for one reputation subject type."""
    return tuple(_DEFAULT_WEIGHTS[subject_type].keys())


async def _raw(db: AsyncSession, key: str) -> str | None:
    """Fetch one raw platform config value by key."""
    statement = select(PlatformConfig.value).where(PlatformConfig.key == key)
    # PlatformConfig.value is an untyped JSON column, so scalar() yields Any.
    return cast("str | None", await db.scalar(statement))


async def load_config(
    db: AsyncSession,
    *,
    subject_type: str,
) -> ReputationConfig:
    """Load one subject's reputation config with default fallback values."""
    raw_weights = await _raw(db, f"reputation_weights_{subject_type}")
    if raw_weights:
        weights_map = {
            key: Decimal(str(value)) for key, value in json.loads(raw_weights).items()
        }
    else:
        weights_map = {
            key: Decimal(value) for key, value in _DEFAULT_WEIGHTS[subject_type].items()
        }
    validate_weight_map(weights_map, subject_type=subject_type)

    min_activity = int(
        await _raw(db, f"reputation_min_activity_{subject_type}")
        or _DEFAULT_MIN_ACTIVITY[subject_type]
    )
    prior = Decimal(await _raw(db, "reputation_prior") or "0.5")
    prior_strength_k = Decimal(await _raw(db, "reputation_prior_strength_k") or "5")
    decay_halflife_days = int(await _raw(db, "reputation_decay_halflife_days") or "180")
    dispute_penalty = Decimal(await _raw(db, "reputation_dispute_penalty") or "0.20")
    reliability_penalty = Decimal(
        await _raw(db, "attestor_reliability_penalty") or "0.10"
    )
    cert_min_attestations = int(
        await _raw(db, "attestor_certification_min_attestations") or "10"
    )
    cert_min_avg_rating = Decimal(
        await _raw(db, "attestor_certification_min_avg_rating") or "4.5"
    )

    if min_activity < 1 or prior_strength_k < 0 or decay_halflife_days < 1:
        raise ValueError(
            "reputation min_activity, prior_strength_k, and halflife must be positive"
        )
    if prior < 0 or prior > 1 or dispute_penalty < 0 or dispute_penalty > 1:
        raise ValueError("reputation prior and dispute penalty must be between 0 and 1")
    if (
        reliability_penalty < 0
        or reliability_penalty > 1
        or cert_min_attestations < 1
        or cert_min_avg_rating < 1
        or cert_min_avg_rating > 5
    ):
        raise ValueError(
            "attestor reliability_penalty must be 0-1, cert_min_attestations >= 1, "
            "and cert_min_avg_rating 1-5"
        )

    return ReputationConfig(
        subject_type=subject_type,
        weights=weights_map,
        min_activity=min_activity,
        prior=prior,
        prior_strength_k=prior_strength_k,
        decay_halflife_days=decay_halflife_days,
        dispute_penalty=dispute_penalty,
        reliability_penalty=reliability_penalty,
        cert_min_attestations=cert_min_attestations,
        cert_min_avg_rating=cert_min_avg_rating,
    )
