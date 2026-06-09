"""Tests for selecting the payment provider for a financial operation."""

from app.integrations.payment_router import select_provider


def test_select_provider_routes_all_phase_three_mvp_payments_to_stripe() -> None:
    """Phase 3 MVP is Stripe-only while regional rails are deferred."""
    assert select_provider(user_country="NG", currency="USD") == "stripe"
    assert select_provider(user_country="US", currency="NGN") == "stripe"
    assert select_provider(user_country="US", currency="USD") == "stripe"
    assert select_provider(user_country=None, currency="USD") == "stripe"
