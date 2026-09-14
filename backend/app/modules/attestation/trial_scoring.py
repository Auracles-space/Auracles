"""Pure grading helpers for the Org Attestor calibration trial.

Compares nominee rubric scores against a fixture answer key and returns a
weighted agreement percentage plus an automatic pass/fail suggestion.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

PASS_THRESHOLD_PCT = 80.0
_SCALE_SPAN = 4.0


def dimension_agreement(nominee: int, expected: int, tolerance: int) -> float:
    """Return normalized agreement for one rubric dimension.

    Args:
        nominee: Nominee score on the 1-5 rubric scale.
        expected: Answer-key score on the 1-5 rubric scale.
        tolerance: Allowed deviation for full credit.

    Returns:
        A float in the inclusive range ``[0.0, 1.0]``.
    """
    delta = abs(nominee - expected)
    if delta <= tolerance:
        return 1.0
    return max(0.0, 1.0 - (delta - tolerance) / _SCALE_SPAN)


def grade(
    nominee_scores: dict[UUID, int],
    answer_key: dict[UUID, tuple[int, int]],
    weights: dict[UUID, Decimal],
) -> tuple[Decimal, str]:
    """Grade a full nominee submission against the answer key.

    Args:
        nominee_scores: Mapping of dimension id to nominee score.
        answer_key: Mapping of dimension id to expected score and tolerance.
        weights: Mapping of dimension id to rubric weight.

    Returns:
        The rounded percentage score and the automatic ``pass``/``fail`` result.

    Raises:
        ValueError: If the inputs do not cover the same dimensions, or the
            total weight is zero.
    """
    dimension_ids = set(nominee_scores)
    if dimension_ids != set(answer_key) or dimension_ids != set(weights):
        raise ValueError(
            "nominee_scores, answer_key, and weights must cover the same dimensions"
        )

    total_weight = sum(weights.values(), Decimal("0"))
    if total_weight <= 0:
        raise ValueError("total rubric weight must be positive")

    earned = Decimal("0")
    for dimension_id in dimension_ids:
        expected_score, tolerance = answer_key[dimension_id]
        agreement = Decimal(
            str(
                dimension_agreement(
                    nominee_scores[dimension_id],
                    expected_score,
                    tolerance,
                )
            )
        )
        earned += weights[dimension_id] * agreement

    score_pct = (earned / total_weight * Decimal("100")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    auto_result = "pass" if score_pct >= Decimal(str(PASS_THRESHOLD_PCT)) else "fail"
    return score_pct, auto_result
