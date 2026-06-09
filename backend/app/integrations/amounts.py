"""Shared amount conversion helpers for payment provider adapters."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

SUPPORTED_MINOR_UNIT_CURRENCIES = {"USD", "NGN"}


class MoneyAmountError(ValueError):
    """Raised when an amount cannot be represented for a provider."""


def to_minor_units(amount: Decimal, currency: str) -> int:
    """Convert a positive two-decimal amount to provider minor units."""
    normalized_currency = currency.strip().upper()
    if normalized_currency not in SUPPORTED_MINOR_UNIT_CURRENCIES:
        raise MoneyAmountError(f"Unsupported currency: {currency}.")
    try:
        cents = amount * Decimal("100")
        if cents != cents.to_integral_exact():
            raise MoneyAmountError("Amount must have at most two decimal places.")
    except InvalidOperation as exc:
        raise MoneyAmountError("Amount must have at most two decimal places.") from exc
    minor_units = int(cents)
    if minor_units <= 0:
        raise MoneyAmountError("Amount must be positive.")
    return minor_units
