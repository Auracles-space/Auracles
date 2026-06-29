"""Tests for the controlled Attestor sector/category taxonomy."""

import pytest

from app.modules.attestation.taxonomy import (
    FRAMEWORK_CATEGORIES,
    validate_categories,
    validate_sectors,
)


def test_known_values_pass_and_dedupe() -> None:
    assert validate_sectors(["PE", "PE", "VC"]) == ["PE", "VC"]
    assert "Compliance" in FRAMEWORK_CATEGORIES


def test_unknown_value_rejected() -> None:
    with pytest.raises(ValueError):
        validate_sectors(["Crypto Hedge Fund"])
    with pytest.raises(ValueError):
        validate_categories(["Astrology"])
