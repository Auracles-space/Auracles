"""Unit tests for the AMM scoring formula and per-factor functions.

Verifies each factor maps inputs to [0,1] per the spec, including the
neutral-on-missing-constraint rules, and that compute_match_score applies the
locked weights.

Maps to: spec §1 (Components) AMM Scoring.
"""

from __future__ import annotations

import pytest

from app.modules.attestation import scoring


def test_weights_sum_to_one():
    """The locked AMM weights must remain normalized."""
    assert pytest.approx(sum(scoring.WEIGHTS.values()), abs=1e-9) == 1.0


def test_swap_point_constants_are_neutral():
    """Missing-data swap points must stay at the neutral 0.5 baseline."""
    assert scoring.CREDENTIAL_RELEVANCE_BASELINE == 0.5
    assert scoring.REPUTATION_BASELINE == 0.5


def test_sector_alignment_full_overlap():
    """Requested sectors fully covered by the profile score 1.0."""
    assert scoring.sector_alignment(["tax", "audit"], ["tax"], ["audit"]) == 1.0


def test_sector_alignment_partial():
    """Partial requested-sector overlap scores the overlap fraction."""
    assert scoring.sector_alignment(["tax", "audit"], ["tax"], []) == 0.5


def test_sector_alignment_no_overlap():
    """No requested-sector overlap scores zero."""
    assert scoring.sector_alignment(["tax"], ["legal"], ["hr"]) == 0.0


def test_sector_alignment_empty_request_is_neutral():
    """Unconstrained requests should not penalize candidates."""
    assert scoring.sector_alignment([], ["tax"], []) == 1.0


def test_category_match_in_set():
    """A matching category scores full credit."""
    assert scoring.category_match("compliance", ["compliance", "tax"]) == 1.0


def test_category_match_not_in_set():
    """A non-matching category scores zero."""
    assert scoring.category_match("compliance", ["tax"]) == 0.0


def test_category_match_none_is_neutral():
    """Non-framework requests treat category as not applicable."""
    assert scoring.category_match(None, []) == 1.0


def test_availability_no_active_is_full():
    """No active assignments leaves full availability."""
    assert scoring.availability_score(0, 5) == 1.0


def test_availability_partial():
    """Availability scales down linearly as active work increases."""
    assert scoring.availability_score(4, 5) == pytest.approx(0.2)


def test_availability_floor_at_zero():
    """At-cap candidates bottom out at zero availability."""
    assert scoring.availability_score(5, 5) == 0.0


def test_compute_match_score_weights_and_breakdown():
    """The weighted sum should use the locked factor keys and weights."""
    factors = {
        "sector": 1.0,
        "category": 1.0,
        "credential": 0.5,
        "availability": 1.0,
        "reputation": 0.5,
    }
    score, breakdown = scoring.compute_match_score(factors)
    assert score == 0.85
    assert breakdown == factors
