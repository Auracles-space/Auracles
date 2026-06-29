"""Controlled Attestor specialisation taxonomy (Module 1.5).

Sector × Framework-Category vocabulary that drives AMM scoring (Module 3).
Replaces the prior free-text specializations.
"""

from __future__ import annotations

SECTORS: frozenset[str] = frozenset({"PE", "VC", "Infrastructure", "Real Estate"})
FRAMEWORK_CATEGORIES: frozenset[str] = frozenset({
    "Compliance", "Governance", "Risk", "Operations", "Legal",
    "Finance", "HR", "Technology", "Investment Management",
})


def _validate(values: list[str], allowed: frozenset[str], label: str) -> list[str]:
    """Trim, de-duplicate (first-seen), and reject values outside ``allowed``."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = raw.strip()
        if item not in allowed:
            raise ValueError(f"{item!r} is not a valid {label}.")
        if item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    if not cleaned:
        raise ValueError(f"at least one {label} is required.")
    return cleaned


def validate_sectors(values: list[str]) -> list[str]:
    """Validate sector tags against the controlled set."""
    return _validate(values, SECTORS, "sector")


def validate_categories(values: list[str]) -> list[str]:
    """Validate framework-category tags against the controlled set."""
    return _validate(values, FRAMEWORK_CATEGORIES, "framework category")
