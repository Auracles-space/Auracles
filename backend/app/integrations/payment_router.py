"""Payment provider routing rules for Auracles financial operations."""

from __future__ import annotations

from typing import Literal

PaymentProvider = Literal["stripe"]


def select_provider(
    *,
    user_country: str | None,
    currency: str,
) -> PaymentProvider:
    """Return Stripe for Phase 3 MVP payment operations.

    Team decision on 2026-06-09 deferred Paystack/NGN rails to a later regional
    payments phase. Keep the country/currency parameters so purchase services
    do not need another interface change when regional routing returns.
    """
    del user_country, currency
    return "stripe"
