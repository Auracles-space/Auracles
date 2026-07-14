"""Verifies the taxonomy-unification remap tables for attestor data."""

from __future__ import annotations

from migrations import attestor_taxonomy_remap as mig


def test_sector_map_is_canonical() -> None:
    """Legacy sector labels map to canonical framework slugs."""
    assert mig.SECTOR_MAP["PE"] == "private_equity"
    assert mig.SECTOR_MAP["Real Estate"] == "real_estate"


def test_function_map_covers_all_nine_legacy_categories() -> None:
    """All nine legacy categories map, including the two semantic misfits."""
    assert mig.FUNCTION_MAP["Technology"] == "engineering"
    assert mig.FUNCTION_MAP["Investment Management"] == "investment_management"
    assert len(mig.FUNCTION_MAP) == 9


def test_remap_array_leaves_unknown_values_untouched() -> None:
    """Unmapped values pass through unchanged so migration never drops data."""
    assert mig._remap_array(["PE", "UnknownSector"], mig.SECTOR_MAP) == [
        "private_equity",
        "UnknownSector",
    ]
