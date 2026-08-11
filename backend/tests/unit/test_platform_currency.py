"""Tests for the single platform settlement currency.

Auracles runs as a single-currency marketplace: one currency is priced,
charged, earned, and paid out in, and every money guard in the codebase
compares against it. The currency lives in one setting so the closed Nigerian
pilot can run on NGN without twenty separate literals drifting apart, and so a
later multi-currency model is an extension rather than a rewrite.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.currency import (
    SUPPORTED_PLATFORM_CURRENCIES,
    normalize_platform_currency,
    platform_currency,
)

# The value declared as the field default in app/core/config.py. Kept in one
# place so the pilot currency has a single source of truth in this module.
_FIELD_DEFAULT_CURRENCY = "NGN"

# Mandatory secrets, so Settings can be constructed without the test env.
_BASE_SETTINGS = {
    "ENVIRONMENT": "local",
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
    "REDIS_URL": "redis://localhost:6379/0",
    "SECRET_KEY": "dev-only-change-me",
    "TOTP_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "PAYOUT_ACCOUNT_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "PARTNER_WEBHOOK_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "S3_ARTIFACTS_BUCKET": "artifacts",
    "S3_AVATARS_BUCKET": "avatars",
    "S3_REPORTS_BUCKET": "reports",
    "S3_THUMBNAILS_BUCKET": "thumbnails",
}


def _settings(**overrides: str) -> Settings:
    """Build a Settings instance with the mandatory secrets pre-filled."""
    base = dict(_BASE_SETTINGS)
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_platform_currency_defaults_to_naira(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pilot settles in NGN, so that is the default with no env override.

    Both sides of the closed pilot are Nigerian, so naira is charged and paid
    out without any conversion step existing at all. The env var is removed
    first because conftest pins it to USD for the rest of the suite — without
    that, this would read the test environment and assert nothing.
    """
    monkeypatch.delenv("PLATFORM_CURRENCY", raising=False)

    assert _settings().platform_currency == _FIELD_DEFAULT_CURRENCY


def test_platform_currency_reads_the_env_override() -> None:
    """A deployment can pin a different single currency without a code change."""
    assert _settings(PLATFORM_CURRENCY="USD").platform_currency == "USD"


def test_platform_currency_is_normalized_to_uppercase() -> None:
    """Lowercase configuration must not produce a currency that fails guards."""
    assert _settings(PLATFORM_CURRENCY="ngn").platform_currency == "NGN"


def test_platform_currency_rejects_an_unsettleable_currency() -> None:
    """Boot must fail on a currency no payment adapter can charge.

    A currency that survives config but dies inside `to_minor_units` would
    turn every purchase into a 502 at runtime instead of a startup error.
    """
    with pytest.raises(ValidationError):
        _settings(PLATFORM_CURRENCY="GBP")


def test_supported_currencies_match_the_provider_adapters() -> None:
    """The settleable set cannot drift from what the adapters can convert."""
    from app.integrations.amounts import SUPPORTED_MINOR_UNIT_CURRENCIES

    assert SUPPORTED_PLATFORM_CURRENCIES == SUPPORTED_MINOR_UNIT_CURRENCIES


def test_normalize_platform_currency_accepts_the_configured_currency() -> None:
    """Case-insensitive input resolves to the canonical uppercase code.

    Written against the configured currency rather than a literal: the suite
    runs on USD while the pilot runs on NGN, and the contract is the same.
    """
    configured = platform_currency()

    assert normalize_platform_currency(configured.lower()) == configured
    assert normalize_platform_currency(configured) == configured


def test_normalize_platform_currency_rejects_any_other_currency() -> None:
    """A single-currency platform refuses money it cannot settle."""
    configured = platform_currency()
    other = next(code for code in SUPPORTED_PLATFORM_CURRENCIES if code != configured)

    with pytest.raises(ValueError, match=configured):
        normalize_platform_currency(other)


def test_platform_currency_helper_reads_settings() -> None:
    """The helper is the one read point every money guard shares.

    Asserted against the resolved setting rather than a literal: the suite runs
    on USD (see tests/conftest.py) while the pilot deployment runs on NGN, and
    the helper's contract is to report whichever is configured.
    """
    from app.core.config import get_settings

    assert platform_currency() == get_settings().platform_currency
