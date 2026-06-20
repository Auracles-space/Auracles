"""Tests for the Stripe provider integration adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from app.core.config import Settings
from app.integrations.stripe import (
    StripeProviderError,
    create_customer,
    create_payment_intent,
    create_refund,
    create_setup_intent,
    detach_payment_method,
    list_payment_methods,
    make_test_signature_header,
    verify_webhook,
)

STRIPE_SETTINGS = Settings(
    STRIPE_SECRET_KEY="sk_test_123",
    STRIPE_WEBHOOK_SECRET="whsec_test_123",
)


@pytest.mark.asyncio
@respx.mock
async def test_stripe_creates_payment_intent_with_minor_units_and_metadata() -> None:
    """PaymentIntent creation sends cents and Auracles transaction metadata."""
    route = respx.post("https://api.stripe.com/v1/payment_intents").mock(
        return_value=httpx.Response(
            200,
            json={"id": "pi_123", "client_secret": "pi_123_secret_456"},
        )
    )

    result = await create_payment_intent(
        customer_id="cus_123",
        amount=Decimal("25.50"),
        currency="USD",
        metadata={"transaction_id": "txn_123", "kind": "purchase"},
        settings=STRIPE_SETTINGS,
    )

    assert result.id == "pi_123"
    assert result.client_secret == "pi_123_secret_456"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer sk_test_123"
    form = parse_qs(request.content.decode())
    assert form["amount"] == ["2550"]
    assert form["currency"] == ["usd"]
    assert form["customer"] == ["cus_123"]
    assert form["metadata[transaction_id]"] == ["txn_123"]
    assert form["metadata[kind]"] == ["purchase"]


@pytest.mark.asyncio
@respx.mock
async def test_stripe_create_customer_and_refund_use_idempotency_keys() -> None:
    """Customer and refund helpers normalize provider responses and headers."""
    customer_route = respx.post("https://api.stripe.com/v1/customers").mock(
        return_value=httpx.Response(200, json={"id": "cus_123"})
    )
    refund_route = respx.post("https://api.stripe.com/v1/refunds").mock(
        return_value=httpx.Response(200, json={"id": "re_123", "status": "succeeded"})
    )

    customer = await create_customer(
        email="operator@example.com",
        name="Operator One",
        idempotency_key="customer:user_123",
        settings=STRIPE_SETTINGS,
    )
    refund = await create_refund(
        payment_intent_id="pi_123",
        amount=Decimal("10.00"),
        currency="USD",
        idempotency_key="refund:txn_123",
        settings=STRIPE_SETTINGS,
    )

    assert customer.id == "cus_123"
    assert refund.id == "re_123"
    assert customer_route.calls.last.request.headers["Idempotency-Key"] == (
        "customer:user_123"
    )
    assert refund.status == "succeeded"
    assert parse_qs(customer_route.calls.last.request.content.decode())["email"] == [
        "operator@example.com"
    ]
    assert refund_route.calls.last.request.headers["Idempotency-Key"] == (
        "refund:txn_123"
    )


@pytest.mark.asyncio
@respx.mock
async def test_stripe_setup_intent_and_payment_methods_are_provider_held() -> None:
    """SetupIntent/list/detach helpers expose only non-sensitive card metadata."""
    setup_route = respx.post("https://api.stripe.com/v1/setup_intents").mock(
        return_value=httpx.Response(
            200,
            json={"id": "seti_123", "client_secret": "seti_123_secret_456"},
        )
    )
    list_route = respx.get("https://api.stripe.com/v1/payment_methods").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "pm_123",
                        "type": "card",
                        "card": {
                            "brand": "visa",
                            "last4": "4242",
                            "exp_month": 8,
                            "exp_year": 2028,
                        },
                    }
                ]
            },
        )
    )
    detach_route = respx.post(
        "https://api.stripe.com/v1/payment_methods/pm_123/detach"
    ).mock(return_value=httpx.Response(200, json={"id": "pm_123"}))

    setup_intent = await create_setup_intent(
        customer_id="cus_123",
        settings=STRIPE_SETTINGS,
    )
    payment_methods = await list_payment_methods(
        customer_id="cus_123",
        settings=STRIPE_SETTINGS,
    )
    detached = await detach_payment_method(
        payment_method_id="pm_123",
        settings=STRIPE_SETTINGS,
    )

    assert setup_intent.id == "seti_123"
    assert setup_intent.client_secret == "seti_123_secret_456"
    setup_form = parse_qs(setup_route.calls.last.request.content.decode())
    assert setup_form["customer"] == ["cus_123"]
    assert setup_form["usage"] == ["off_session"]
    assert setup_form["automatic_payment_methods[enabled]"] == ["true"]
    assert payment_methods[0].id == "pm_123"
    assert payment_methods[0].brand == "visa"
    assert payment_methods[0].last4 == "4242"
    assert list_route.calls.last.request.url.params["customer"] == "cus_123"
    assert detached == "pm_123"
    assert detach_route.called


def test_stripe_webhook_signature_matrix_accepts_only_valid_raw_payload() -> None:
    """Webhook verification requires the raw body and a valid v1 signature."""
    payload = json.dumps(
        {"id": "evt_123", "type": "payment_intent.succeeded"},
        separators=(",", ":"),
    ).encode()
    now = datetime(2026, 6, 9, tzinfo=UTC)
    signature = make_test_signature_header(
        payload,
        secret="whsec_test_123",
        timestamp=int(now.timestamp()),
    )

    event = verify_webhook(
        payload,
        signature,
        settings=STRIPE_SETTINGS,
        now=now,
    )

    assert event["id"] == "evt_123"

    with pytest.raises(StripeProviderError):
        verify_webhook(
            payload,
            signature.replace("v1=", "v1=bad"),
            settings=STRIPE_SETTINGS,
            now=now,
        )


def test_stripe_webhook_multiple_secrets() -> None:
    """Webhook verification accepts signatures matching any of the comma-separated secrets."""
    payload = json.dumps(
        {"id": "evt_123", "type": "payment_intent.succeeded"},
        separators=(",", ":"),
    ).encode()
    now = datetime(2026, 6, 9, tzinfo=UTC)

    # Configure multiple secrets in settings
    multi_settings = Settings(
        STRIPE_SECRET_KEY="sk_test_123",
        STRIPE_WEBHOOK_SECRET="whsec_first_secret, whsec_second_secret",
    )

    # Signature generated with the first secret
    sig1 = make_test_signature_header(
        payload,
        secret="whsec_first_secret",
        timestamp=int(now.timestamp()),
    )
    # Signature generated with the second secret
    sig2 = make_test_signature_header(
        payload,
        secret="whsec_second_secret",
        timestamp=int(now.timestamp()),
    )

    # Both should pass
    event1 = verify_webhook(payload, sig1, settings=multi_settings, now=now)
    event2 = verify_webhook(payload, sig2, settings=multi_settings, now=now)

    assert event1["id"] == "evt_123"
    assert event2["id"] == "evt_123"

    # An invalid signature should still fail
    with pytest.raises(StripeProviderError):
        verify_webhook(
            payload,
            sig1.replace("v1=", "v1=bad"),
            settings=multi_settings,
            now=now,
        )

