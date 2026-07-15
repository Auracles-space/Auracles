"""Unit tests for the pure calibration-trial grading engine."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.modules.attestation import trial_scoring


def test_exact_match_scores_100() -> None:
    """Every dimension exactly on the key yields 100% and pass."""
    d1, d2 = uuid4(), uuid4()

    pct, result = trial_scoring.grade(
        nominee_scores={d1: 4, d2: 2},
        answer_key={d1: (4, 0), d2: (2, 0)},
        weights={d1: Decimal("0.5"), d2: Decimal("0.5")},
    )

    assert pct == Decimal("100.00")
    assert result == "pass"


def test_within_tolerance_full_credit() -> None:
    """A score inside the tolerance band earns full credit."""
    d1 = uuid4()

    pct, result = trial_scoring.grade(
        nominee_scores={d1: 3},
        answer_key={d1: (4, 1)},
        weights={d1: Decimal("1.0")},
    )

    assert pct == Decimal("100.00")
    assert result == "pass"


def test_large_deviation_decays_and_weights() -> None:
    """Out-of-tolerance deviation decays linearly and respects weights."""
    d1, d2 = uuid4(), uuid4()

    pct, result = trial_scoring.grade(
        nominee_scores={d1: 1, d2: 3},
        answer_key={d1: (5, 0), d2: (3, 0)},
        weights={d1: Decimal("0.5"), d2: Decimal("0.5")},
    )

    assert pct == Decimal("50.00")
    assert result == "fail"


def test_threshold_boundary() -> None:
    """79.99% fails while 80.00% passes."""
    d1, d2 = uuid4(), uuid4()

    below_pct, below_result = trial_scoring.grade(
        nominee_scores={d1: 5, d2: 1},
        answer_key={d1: (5, 0), d2: (5, 0)},
        weights={d1: Decimal("0.7999"), d2: Decimal("0.2001")},
    )
    at_pct, at_result = trial_scoring.grade(
        nominee_scores={d1: 5, d2: 1},
        answer_key={d1: (5, 0), d2: (5, 0)},
        weights={d1: Decimal("0.8"), d2: Decimal("0.2")},
    )

    assert below_pct == Decimal("79.99")
    assert below_result == "fail"
    assert at_pct == Decimal("80.00")
    assert at_result == "pass"
