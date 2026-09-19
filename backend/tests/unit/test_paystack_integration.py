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
    create_transfer_recipient,
    fetch_transaction,
    initialize_transaction,
    initiate_transfer,
    list_banks,
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


@pytest.mark.asyncio
@respx.mock
async def test_paystack_creates_nuban_transfer_recipient() -> None:
    """Recipient creation returns the code every later transfer is keyed by.

    A NUBAN recipient is the payout destination for a Nigerian bank account.
    Paystack validates the account number during creation, so a successful
    response is also the account's verification.
    """
    route = respx.post("https://api.paystack.co/transferrecipient").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": True,
                "data": {
                    "recipient_code": "RCP_abc123",
                    "details": {
                        "account_name": "ADA LOVELACE",
                        "account_number": "0123456789",
                        "bank_code": "044",
                    },
                },
            },
        )
    )

    result = await create_transfer_recipient(
        name="Ada Lovelace",
        account_number="0123456789",
        bank_code="044",
        currency="NGN",
        settings=PAYSTACK_SETTINGS,
    )

    assert result.recipient_code == "RCP_abc123"
    # The bank-confirmed name is what the Contributor sees before they can
    # request money — it is how they catch a mistyped account number.
    assert result.account_name == "ADA LOVELACE"
    assert json.loads(route.calls.last.request.content) == {
        "type": "nuban",
        "name": "Ada Lovelace",
        "account_number": "0123456789",
        "bank_code": "044",
        "currency": "NGN",
    }


@pytest.mark.asyncio
@respx.mock
async def test_paystack_transfer_recipient_rejects_a_response_without_a_code() -> None:
    """A recipient with no code cannot be paid, so it must not be stored."""
    respx.post("https://api.paystack.co/transferrecipient").mock(
        return_value=httpx.Response(
            200,
            json={"status": True, "data": {"details": {"account_name": "ADA"}}},
        )
    )

    with pytest.raises(PaystackProviderError, match="recipient"):
        await create_transfer_recipient(
            name="Ada Lovelace",
            account_number="0123456789",
            bank_code="044",
            currency="NGN",
            settings=PAYSTACK_SETTINGS,
        )


@pytest.mark.asyncio
@respx.mock
async def test_paystack_initiates_transfer_in_minor_units_with_our_reference() -> None:
    """Transfers send kobo and carry our own reference for idempotent retries."""
    route = respx.post("https://api.paystack.co/transfer").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": True,
                "data": {
                    "id": 98765,
                    "status": "pending",
                    "transfer_code": "TRF_xyz",
                },
            },
        )
    )

    result = await initiate_transfer(
        amount=Decimal("50000.00"),
        currency="NGN",
        recipient="RCP_abc123",
        reason="Auracles payout",
        reference="payout-1234",
        settings=PAYSTACK_SETTINGS,
    )

    assert result.id == "98765"
    assert result.status == "pending"
    assert result.transfer_code == "TRF_xyz"
    assert json.loads(route.calls.last.request.content) == {
        "source": "balance",
        "amount": 5000000,
        "currency": "NGN",
        "recipient": "RCP_abc123",
        "reason": "Auracles payout",
        "reference": "payout-1234",
    }


@pytest.mark.asyncio
@respx.mock
async def test_paystack_lists_banks_for_the_payout_country() -> None:
    """The bank list is fetched from Paystack, never hardcoded.

    Bank codes change and new institutions appear; a stale local list would
    send a Contributor's money to the wrong institution or reject a valid one.
    """
    route = respx.get("https://api.paystack.co/bank").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": True,
                "data": [
                    {"name": "Access Bank", "code": "044", "currency": "NGN"},
                    {"name": "Kuda Bank", "code": "50211", "currency": "NGN"},
                ],
            },
        )
    )

    banks = await list_banks(country="nigeria", settings=PAYSTACK_SETTINGS)

    assert [(bank.name, bank.code) for bank in banks] == [
        ("Access Bank", "044"),
        ("Kuda Bank", "50211"),
    ]
    assert route.calls.last.request.url.params["country"] == "nigeria"


@pytest.mark.asyncio
@respx.mock
async def test_paystack_list_banks_skips_malformed_entries() -> None:
    """One unusable entry must not deny the Contributor the whole bank list."""
    respx.get("https://api.paystack.co/bank").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": True,
                "data": [
                    {"name": "Access Bank", "code": "044"},
                    {"name": "Broken Bank"},
                    {"code": "999"},
                ],
            },
        )
    )

    banks = await list_banks(country="nigeria", settings=PAYSTACK_SETTINGS)

    assert [bank.code for bank in banks] == ["044"]


@pytest.mark.asyncio
@respx.mock
async def test_paystack_list_banks_drops_exact_duplicates() -> None:
    """Paystack repeats some banks verbatim; each name and code pair appears once.

    Two different institutions sharing a code both stay listed.
    """
    respx.get("https://api.paystack.co/bank").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": True,
                "data": [
                    {"name": "Zenith Bank", "code": "057"},
                    {"name": "Zenith Bank", "code": "057"},
                    {"name": "Alpha Microfinance Bank", "code": "50572"},
                    {"name": "Beta Microfinance Bank", "code": "50572"},
                ],
            },
        )
    )

    banks = await list_banks(country="nigeria", settings=PAYSTACK_SETTINGS)

    assert [(bank.name, bank.code) for bank in banks] == [
        ("Zenith Bank", "057"),
        ("Alpha Microfinance Bank", "50572"),
        ("Beta Microfinance Bank", "50572"),
    ]


@pytest.mark.asyncio
@respx.mock
async def test_paystack_fetches_a_transaction_fee_by_reference() -> None:
    """The verify lookup returns the fee Paystack kept, in minor units."""
    respx.get("https://api.paystack.co/transaction/verify/sale-ref-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": True,
                "data": {
                    "reference": "sale-ref-1",
                    "status": "success",
                    "currency": "NGN",
                    "amount": 1000000,
                    "fees": 15000,
                    "paid_at": "2026-08-01T10:15:00.000Z",
                },
            },
        )
    )

    result = await fetch_transaction(reference="sale-ref-1", settings=PAYSTACK_SETTINGS)

    assert result.reference == "sale-ref-1"
    assert result.status == "success"
    assert result.currency == "NGN"
    assert result.fees_minor == 15000
    assert result.paid_at is not None
    assert result.paid_at.isoformat() == "2026-08-01T10:15:00+00:00"


@pytest.mark.asyncio
@respx.mock
async def test_paystack_transaction_without_a_fee_reports_none() -> None:
    """A transaction with no fee field reports no fee rather than zero."""
    respx.get("https://api.paystack.co/transaction/verify/abandoned-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": True,
                "data": {"reference": "abandoned-1", "status": "abandoned"},
            },
        )
    )

    result = await fetch_transaction(
        reference="abandoned-1", settings=PAYSTACK_SETTINGS
    )

    assert result.fees_minor is None
    assert result.paid_at is None


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


@pytest.mark.asyncio
@respx.mock
async def test_a_refused_transfer_keeps_paystack_s_own_explanation() -> None:
    """A refusal carries the provider's message, not just its status code.

    Paystack refuses a transfer it cannot fund with a 400 and an explanation
    in the body. Discarding that leaves every 400 looking alike, so a payout
    waiting on the platform balance cannot be told apart from a genuinely
    broken request — and the difference decides whether retrying can ever
    succeed.
    """
    respx.post("https://api.paystack.co/transfer").mock(
        return_value=httpx.Response(
            400,
            json={
                "status": False,
                "message": "Your balance is not enough to fulfil this request",
            },
        )
    )

    with pytest.raises(PaystackProviderError) as caught:
        await initiate_transfer(
            amount=Decimal("315000.00"),
            currency="NGN",
            recipient="RCP_test",
            reason="Auracles payout",
            reference="payout-test",
            settings=PAYSTACK_SETTINGS,
        )

    assert caught.value.status_code == 400
    assert caught.value.message == "Your balance is not enough to fulfil this request"
    assert caught.value.insufficient_balance is True


@pytest.mark.asyncio
@respx.mock
async def test_an_unrelated_refusal_is_not_read_as_a_funding_problem() -> None:
    """Only a balance refusal defers a payout; everything else is a real error.

    Treating an ordinary rejection as a funding shortfall would leave a
    broken payout retrying hourly forever while telling the contributor to
    wait for money that was never the problem.
    """
    respx.post("https://api.paystack.co/transfer").mock(
        return_value=httpx.Response(
            400,
            json={"status": False, "message": "Recipient specified does not exist"},
        )
    )

    with pytest.raises(PaystackProviderError) as caught:
        await initiate_transfer(
            amount=Decimal("100.00"),
            currency="NGN",
            recipient="RCP_missing",
            reason="Auracles payout",
            reference="payout-test-2",
            settings=PAYSTACK_SETTINGS,
        )

    assert caught.value.insufficient_balance is False
