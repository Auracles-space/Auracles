"""Unit tests for the seeded attestation review rubrics."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.attestation import rubrics


def test_every_review_type_weights_sum_to_one() -> None:
    """Each review_type's dimension weights must sum to exactly 1.000."""
    for review_type, dims in rubrics.RUBRICS.items():
        total = sum((dimension.weight for dimension in dims), Decimal("0"))
        assert total == Decimal("1.000"), f"{review_type} sums to {total}"


def test_quality_has_eight_dimensions() -> None:
    """Quality rubric mirrors workflow section 4.2's eight-dimension set."""
    keys = [dimension.key for dimension in rubrics.RUBRICS["quality"]]
    assert keys == [
        "completeness",
        "implementability",
        "accuracy",
        "clarity",
        "version_currency",
        "appropriate_scope",
        "risk_flags",
        "recommended_use_cases",
    ]


def test_weighted_overall_all_fives_is_five() -> None:
    """A perfect score across every dimension yields 5.00."""
    scores = {dimension.key: 5 for dimension in rubrics.RUBRICS["provenance"]}
    assert rubrics.weighted_overall(scores, "provenance") == Decimal("5.00")


def test_weighted_overall_rejects_missing_dimension() -> None:
    """Missing a dimension score is a programming error, not a silent 0."""
    with pytest.raises(ValueError):
        rubrics.weighted_overall({"authorship_verification": 5}, "provenance")


def test_weighted_overall_rejects_out_of_range() -> None:
    """Scores outside 1-5 raise."""
    scores = {dimension.key: 5 for dimension in rubrics.RUBRICS["quality"]}
    scores["clarity"] = 6
    with pytest.raises(ValueError):
        rubrics.weighted_overall(scores, "quality")


def test_every_type_has_methodology() -> None:
    """Every review_type carries canned section 4.6(c) methodology text."""
    for review_type in rubrics.RUBRICS:
        assert rubrics.METHODOLOGY[review_type].strip()
