"""Pure scoring helpers for AMM-based Attestor matching.

Implements the locked weighted scoring formula used to rank eligible Attestors
for an Attestation request. The module is intentionally dependency-free so the
formula can be unit tested in isolation.
"""

from __future__ import annotations

from typing import Final

WEIGHTS: Final[dict[str, float]] = {
    "sector": 0.30,
    "category": 0.25,
    "credential": 0.20,
    "availability": 0.15,
    "reputation": 0.10,
}

CREDENTIAL_RELEVANCE_BASELINE: Final[float] = 0.5
REPUTATION_BASELINE: Final[float] = 0.5


def sector_alignment(
    requested: list[str],
    profile_sectors: list[str],
    profile_specializations: list[str],
) -> float:
    """Score overlap between requested sectors and the profile's expertise.

    Args:
        requested: Sectors or specializations requested on the Attestation.
        profile_sectors: Sector tags on the Attestor profile.
        profile_specializations: Specialization tags on the Attestor profile.

    Returns:
        A score in the inclusive range [0.0, 1.0].
    """
    if not requested:
        return 1.0
    requested_set = {value.casefold() for value in requested}
    profile_set = {
        value.casefold() for value in [*profile_sectors, *profile_specializations]
    }
    overlap = requested_set & profile_set
    return len(overlap) / len(requested_set)


def category_match(
    framework_category: str | None,
    profile_framework_categories: list[str],
) -> float:
    """Score whether a framework request category matches the profile.

    Args:
        framework_category: The framework category for framework-target requests.
        profile_framework_categories: Categories listed on the Attestor profile.

    Returns:
        ``1.0`` when the category matches, ``0.0`` when it does not, and
        ``1.0`` when no category applies to the request.
    """
    if framework_category is None:
        return 1.0
    categories = {value.casefold() for value in profile_framework_categories}
    return 1.0 if framework_category.casefold() in categories else 0.0


def availability_score(active_count: int, cap: int) -> float:
    """Convert active-assignment load into an availability factor.

    Args:
        active_count: Number of live assignments held by the Attestor.
        cap: Maximum allowed concurrent assignments.

    Returns:
        A score in the inclusive range [0.0, 1.0].

    Raises:
        ValueError: If ``cap`` is less than 1.
    """
    if cap < 1:
        raise ValueError("cap must be at least 1.")
    return max(0.0, (cap - active_count) / cap)


def credential_relevance() -> float:
    """Return the neutral credential-relevance swap point."""
    return CREDENTIAL_RELEVANCE_BASELINE


def reputation_score() -> float:
    """Return the neutral reputation swap point."""
    return REPUTATION_BASELINE


def compute_match_score(factors: dict[str, float]) -> tuple[float, dict[str, float]]:
    """Compute the weighted AMM match score and persistable factor breakdown.

    Args:
        factors: Mapping of factor name to a score in the inclusive range
            [0.0, 1.0]. Must contain every key in ``WEIGHTS``.

    Returns:
        A rounded weighted score and a shallow copy of the factor breakdown.

    Raises:
        ValueError: If any required factor is missing.
    """
    missing = [key for key in WEIGHTS if key not in factors]
    if missing:
        raise ValueError(f"missing factors: {', '.join(missing)}")
    weighted = sum(WEIGHTS[key] * factors[key] for key in WEIGHTS)
    return round(weighted, 3), dict(factors)
