"""Payment provider routing rules for Auracles financial operations."""

from __future__ import annotations

from typing import Literal

PaymentProvider = Literal["stripe", "paystack"]

NIGERIA_COUNTRY_CODE = "NG"
NAIRA_CURRENCY_CODE = "NGN"


def select_provider(
    *,
    user_country: str | None,
    currency: str,
) -> PaymentProvider:
    """Return the payment provider that should settle this operation.

    The Nigerian corridor settles on Paystack — local card rails, local bank
    payouts — and everything else on Stripe. Country is checked as well as
    currency because Frameworks are priced in USD today, so a currency-only
    rule would never route a Nigerian payer to the local rail.

    Args:
        user_country: ISO 3166-1 alpha-2 country of the paying party, or None
            when the payer has not recorded one.
        currency: ISO 4217 code the operation is denominated in.

    Returns:
        The provider slug to stamp on the transaction and charge through.
    """
    if user_country == NIGERIA_COUNTRY_CODE:
        return "paystack"
    if currency.upper() == NAIRA_CURRENCY_CODE:
        return "paystack"
    return "stripe"
