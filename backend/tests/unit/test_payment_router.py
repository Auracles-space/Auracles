"""Tests for selecting the payment provider for a financial operation."""

from app.integrations.payment_router import select_provider


def test_select_provider_routes_ngn_or_nigerian_users_to_paystack() -> None:
    """Nigeria-local users and NGN payments should use Paystack rails."""
    assert select_provider(user_country="NG", currency="USD") == "paystack"
    assert select_provider(user_country="US", currency="NGN") == "paystack"


def test_select_provider_routes_other_payments_to_stripe() -> None:
    """Non-NGN payments outside Nigeria use Stripe by default."""
    assert select_provider(user_country="US", currency="USD") == "stripe"
    assert select_provider(user_country=None, currency="USD") == "stripe"
