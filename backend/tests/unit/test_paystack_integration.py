"""Tests for the Paystack provider integration adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

import httpx
import pytest
import respx

from app.core.config import Settings
from app.integrations.paystack import (
    PaystackProviderError,
    create_subaccount,
    initialize_transaction,
    verify_webhook,
)

PAYSTACK_SETTINGS = Settings(
    PAYSTACK_SECRET_KEY="sk_test_paystack",
    PAYSTACK_WEBHOOK_SECRET="sk_test_paystack",
)


@pytest.mark.asyncio
@respx.mock
async def test_paystack_initializes_transaction_with_minor_units_and_metadata() -> None:
    """Transaction initialization sends kobo/cents and returns access data."""
    route = respx.post("https://api.paystack.co/transaction/initialize").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": True,
                "data": {
                    "reference": "txn_ref_123",
                    "authorization_url": "https://checkout.paystack.com/abc",
                    "access_code": "access_123",
                },
            },
        )
    )

    result = await initialize_transaction(
        email="operator@example.com",
        amount=Decimal("2500.00"),
        currency="NGN",
        metadata={"transaction_id": "txn_123", "kind": "purchase"},
        settings=PAYSTACK_SETTINGS,
    )

    assert result.reference == "txn_ref_123"
    assert result.authorization_url == "https://checkout.paystack.com/abc"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer sk_test_paystack"
    assert json.loads(request.content) == {
        "email": "operator@example.com",
        "amount": 250000,
        "currency": "NGN",
        "metadata": {"transaction_id": "txn_123", "kind": "purchase"},
    }


@pytest.mark.asyncio
@respx.mock
async def test_paystack_creates_subaccount_for_provider_hosted_onboarding() -> None:
    """Subaccount creation returns the provider account code we store later."""
    route = respx.post("https://api.paystack.co/subaccount").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": True,
                "data": {"subaccount_code": "ACCT_123", "id": 456},
            },
        )
    )

    result = await create_subaccount(
        business_name="Auracles Contributor",
        bank_code="044",
        account_number="0123456789",
        percentage_charge=0,
        settings=PAYSTACK_SETTINGS,
    )

    assert result.provider_account_id == "ACCT_123"
    assert json.loads(route.calls.last.request.content)["bank_code"] == "044"


def test_paystack_webhook_signature_matrix_accepts_only_valid_raw_payload() -> None:
    """Paystack webhook verification uses HMAC-SHA512 over the raw body."""
    payload = json.dumps(
        {"event": "charge.success", "data": {"reference": "txn_ref_123"}},
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        b"sk_test_paystack",
        payload,
        hashlib.sha512,
    ).hexdigest()

    event = verify_webhook(payload, signature, settings=PAYSTACK_SETTINGS)

    assert event["event"] == "charge.success"

    with pytest.raises(PaystackProviderError):
        verify_webhook(payload, "bad-signature", settings=PAYSTACK_SETTINGS)
