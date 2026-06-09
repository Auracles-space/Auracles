"""Payment provider routing rules for Auracles financial operations."""

from __future__ import annotations

from typing import Literal

PaymentProvider = Literal["stripe", "paystack"]


def select_provider(
    *,
    user_country: str | None,
    currency: str,
) -> PaymentProvider:
    """Return the provider for a payment based on country and currency.

    Paystack owns Nigeria-local and NGN rails. Stripe handles all other
    currently-supported card payments.
    """
    normalized_country = (user_country or "").strip().upper()
    normalized_currency = currency.strip().upper()
    if normalized_country == "NG" or normalized_currency == "NGN":
        return "paystack"
    return "stripe"
