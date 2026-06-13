"""Unit tests for reputation configuration loading and validation.

Phase 5e Slice 2 starts by locking the reputation config loader contract so
later scoring math can rely on stable defaults and input validation.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.admin import service as admin_service
from app.modules.reputation import weights


@pytest.mark.asyncio
async def test_load_config_uses_defaults_when_platform_config_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loader falls back to shipped defaults when no config rows exist."""

    async def fake_raw(_db: object, _key: str) -> str | None:
        """Simulate a database with no reputation config overrides."""
        return None

    monkeypatch.setattr(weights, "_raw", fake_raw)

    config = await weights.load_config(object(), subject_type="framework")

    assert config.subject_type == "framework"
    assert config.weights == {
        "reviews": Decimal("0.35"),
        "attestations": Decimal("0.30"),
        "adoption": Decimal("0.35"),
        "completion": Decimal("0.00"),
        "recency": Decimal("0.00"),
    }
    assert sum(config.weights.values()) == Decimal("1.00")
    assert config.min_activity == 3
    assert config.prior == Decimal("0.5")
    assert config.prior_strength_k == Decimal("5")
    assert config.decay_halflife_days == 180
    assert config.dispute_penalty == Decimal("0.20")


def test_validate_weight_map_rejects_non_unit_sum() -> None:
    """Weight validation rejects factor sets that do not sum to one."""
    with pytest.raises(ValueError, match="sum to 1.0"):
        weights.validate_weight_map(
            {
                "reviews": Decimal("0.30"),
                "attestations": Decimal("0.30"),
                "adoption": Decimal("0.20"),
                "completion": Decimal("0.00"),
                "recency": Decimal("0.00"),
            },
            subject_type="framework",
        )


def test_admin_normalises_reputation_weight_config_json() -> None:
    """Admin config accepts exact reputation factor JSON and stores it stably."""
    value = admin_service._normalise_platform_config_value(
        "reputation_weights_framework",
        (
            '{"reviews":"0.3500","attestations":"0.3000",'
            '"adoption":"0.3500","completion":"0.0000","recency":"0.0000"}'
        ),
    )

    assert value == (
        '{"adoption":"0.3500","attestations":"0.3000",'
        '"completion":"0.0000","recency":"0.0000","reviews":"0.3500"}'
    )


@pytest.mark.parametrize(
    ("key", "raw_value", "expected"),
    [
        ("reputation_prior", "0.65", "0.65"),
        ("reputation_min_activity_framework", "4", "4"),
        ("reputation_prior_strength_k", "6.5000", "6.5"),
        ("reputation_dispute_penalty", "0.15", "0.15"),
    ],
)
def test_admin_normalises_reputation_scalar_config_keys(
    key: str,
    raw_value: str,
    expected: str,
) -> None:
    """Admin config normalises reputation scalar overrides by type."""
    assert admin_service._normalise_platform_config_value(key, raw_value) == expected


def test_admin_rejects_invalid_reputation_weight_factor_set() -> None:
    """Admin config rejects weight JSON with missing or extra reputation factors."""
    with pytest.raises(HTTPException, match="must contain exactly these factors"):
        admin_service._normalise_platform_config_value(
            "reputation_weights_framework",
            '{"reviews":"0.50","attestations":"0.50"}',
        )


@pytest.mark.parametrize(
    ("key", "raw_value", "detail"),
    [
        ("reputation_prior", "1.50", "reputation_prior must be between 0 and 1."),
        (
            "reputation_min_activity_framework",
            "0",
            "reputation_min_activity_framework must be at least 1.",
        ),
        (
            "reputation_prior_strength_k",
            "-1",
            "reputation_prior_strength_k must be greater than or equal to 0.",
        ),
        (
            "reputation_dispute_penalty",
            "-0.1",
            "reputation_dispute_penalty must be between 0 and 1.",
        ),
    ],
)
def test_admin_rejects_invalid_reputation_scalar_config_values(
    key: str,
    raw_value: str,
    detail: str,
) -> None:
    """Admin config enforces reputation scalar bounds before persistence."""
    with pytest.raises(HTTPException, match=detail):
        admin_service._normalise_platform_config_value(key, raw_value)


def test_admin_rejects_decay_halflife_until_decay_is_implemented() -> None:
    """Admin config must not expose a no-op decay knob before the engine uses it."""
    with pytest.raises(HTTPException, match="is not editable"):
        admin_service._normalise_platform_config_value(
            "reputation_decay_halflife_days",
            "365",
        )
