"""Tests for selecting the payment provider for a financial operation."""

from app.integrations.payment_router import select_provider


def test_select_provider_routes_nigerian_payers_to_paystack() -> None:
    """A Nigerian payer settles on the local rail regardless of price currency.

    Frameworks are priced in USD today, so country is the signal that decides
    the rail — currency alone would never route anyone to Paystack.
    """
    assert select_provider(user_country="NG", currency="USD") == "paystack"


def test_select_provider_routes_ngn_prices_to_paystack() -> None:
    """An NGN-denominated charge routes locally whoever the payer is."""
    assert select_provider(user_country="US", currency="NGN") == "paystack"
    assert select_provider(user_country=None, currency="ngn") == "paystack"


def test_select_provider_routes_everything_else_to_stripe() -> None:
    """Stripe stays the default rail outside the Nigerian corridor."""
    assert select_provider(user_country="US", currency="USD") == "stripe"
    assert select_provider(user_country="GB", currency="USD") == "stripe"
    assert select_provider(user_country=None, currency="USD") == "stripe"
