"""Paystack HTTP adapter for NGN payments, refunds, payouts, and webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.integrations.amounts import MoneyAmountError, to_minor_units

PAYSTACK_API_BASE_URL = "https://api.paystack.co"
PAYSTACK_TIMEOUT_SECONDS = 15.0


class PaystackProviderError(RuntimeError):
    """Raised when Paystack configuration, requests, or signatures are invalid."""


@dataclass(frozen=True)
class PaystackCustomer:
    """Normalized Paystack customer result."""

    id: str
    customer_code: str


@dataclass(frozen=True)
class PaystackInitializedTransaction:
    """Normalized Paystack transaction initialization result."""

    reference: str
    authorization_url: str
    access_code: str


@dataclass(frozen=True)
class PaystackRefund:
    """Normalized Paystack refund result."""

    id: str
    status: str | None


@dataclass(frozen=True)
class PaystackSubaccount:
    """Normalized Paystack subaccount result."""

    provider_account_id: str


@dataclass(frozen=True)
class PaystackTransfer:
    """Normalized Paystack transfer result."""

    id: str
    status: str | None


def _require_secret_key(settings: Settings) -> str:
    """Return the configured Paystack API key or raise a provider error."""
    if settings.paystack_secret_key is None:
        raise PaystackProviderError("PAYSTACK_SECRET_KEY is not configured.")
    return settings.paystack_secret_key.get_secret_value()


def _webhook_secret(settings: Settings) -> str:
    """Return the Paystack signing secret.

    Paystack signs webhook bodies with the integration secret key. A separate
    env value can override it for tests or future provider changes.
    """
    if settings.paystack_webhook_secret is not None:
        return settings.paystack_webhook_secret.get_secret_value()
    return _require_secret_key(settings)


async def _post_json(
    path: str,
    body: Mapping[str, Any],
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """POST JSON to Paystack and return the nested data object when present."""
    resolved_settings = settings or get_settings()
    headers = {
        "Authorization": f"Bearer {_require_secret_key(resolved_settings)}",
        "Content-Type": "application/json",
    }

    owns_client = client is None
    resolved_client = client or httpx.AsyncClient(timeout=PAYSTACK_TIMEOUT_SECONDS)
    try:
        response = await resolved_client.post(
            f"{PAYSTACK_API_BASE_URL}{path}",
            json=dict(body),
            headers=headers,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PaystackProviderError(
                f"Paystack returned {response.status_code}."
            ) from exc
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("status") is not True:
            raise PaystackProviderError("Paystack returned an unsuccessful response.")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise PaystackProviderError("Paystack response missing data.")
        return data
    except httpx.HTTPError as exc:
        raise PaystackProviderError("Paystack request failed.") from exc
    finally:
        if owns_client:
            await resolved_client.aclose()


async def create_customer(
    *,
    email: str,
    first_name: str | None = None,
    last_name: str | None = None,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> PaystackCustomer:
    """Create a Paystack customer and return its provider identifiers."""
    body: dict[str, str] = {"email": email}
    if first_name:
        body["first_name"] = first_name
    if last_name:
        body["last_name"] = last_name
    data = await _post_json("/customer", body, settings=settings, client=client)
    raw_id = data.get("id")
    customer_code = data.get("customer_code")
    if not isinstance(raw_id, int | str) or not isinstance(customer_code, str):
        raise PaystackProviderError("Paystack customer response missing fields.")
    return PaystackCustomer(id=str(raw_id), customer_code=customer_code)


async def initialize_transaction(
    *,
    email: str,
    amount: Decimal,
    currency: str,
    metadata: Mapping[str, str],
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
    callback_url: str | None = None,
) -> PaystackInitializedTransaction:
    """Initialize a Paystack transaction using integer minor units."""
    try:
        minor_units = to_minor_units(amount, currency)
    except MoneyAmountError as exc:
        raise PaystackProviderError(str(exc)) from exc

    body: dict[str, Any] = {
        "email": email,
        "amount": minor_units,
        "currency": currency.upper(),
        "metadata": dict(metadata),
    }
    if callback_url:
        body["callback_url"] = callback_url
    data = await _post_json(
        "/transaction/initialize",
        body,
        settings=settings,
        client=client,
    )
    reference = data.get("reference")
    authorization_url = data.get("authorization_url")
    access_code = data.get("access_code")
    if not isinstance(reference, str):
        raise PaystackProviderError("Paystack transaction response missing reference.")
    if not isinstance(authorization_url, str):
        raise PaystackProviderError(
            "Paystack transaction response missing authorization URL."
        )
    if not isinstance(access_code, str):
        raise PaystackProviderError("Paystack transaction response missing fields.")
    return PaystackInitializedTransaction(
        reference=reference,
        authorization_url=authorization_url,
        access_code=access_code,
    )


async def refund_transaction(
    *,
    transaction_reference: str,
    amount: Decimal,
    currency: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> PaystackRefund:
    """Create a Paystack refund for a transaction reference."""
    try:
        minor_units = to_minor_units(amount, currency)
    except MoneyAmountError as exc:
        raise PaystackProviderError(str(exc)) from exc

    data = await _post_json(
        "/refund",
        {"transaction": transaction_reference, "amount": minor_units},
        settings=settings,
        client=client,
    )
    raw_id = data.get("id")
    status = data.get("status")
    if not isinstance(raw_id, int | str):
        raise PaystackProviderError("Paystack refund response missing id.")
    return PaystackRefund(
        id=str(raw_id),
        status=status if isinstance(status, str) else None,
    )


async def create_subaccount(
    *,
    business_name: str,
    bank_code: str,
    account_number: str,
    percentage_charge: int,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> PaystackSubaccount:
    """Create a Paystack subaccount for contributor payouts."""
    data = await _post_json(
        "/subaccount",
        {
            "business_name": business_name,
            "bank_code": bank_code,
            "account_number": account_number,
            "percentage_charge": percentage_charge,
        },
        settings=settings,
        client=client,
    )
    subaccount_code = data.get("subaccount_code")
    if not isinstance(subaccount_code, str):
        raise PaystackProviderError("Paystack subaccount response missing code.")
    return PaystackSubaccount(provider_account_id=subaccount_code)


async def initiate_transfer(
    *,
    amount: Decimal,
    currency: str,
    recipient: str,
    reason: str,
    reference: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> PaystackTransfer:
    """Initiate a Paystack transfer to a transfer recipient."""
    try:
        minor_units = to_minor_units(amount, currency)
    except MoneyAmountError as exc:
        raise PaystackProviderError(str(exc)) from exc

    data = await _post_json(
        "/transfer",
        {
            "source": "balance",
            "amount": minor_units,
            "currency": currency.upper(),
            "recipient": recipient,
            "reason": reason,
            "reference": reference,
        },
        settings=settings,
        client=client,
    )
    raw_id = data.get("id")
    status = data.get("status")
    if not isinstance(raw_id, int | str):
        raise PaystackProviderError("Paystack transfer response missing id.")
    return PaystackTransfer(
        id=str(raw_id),
        status=status if isinstance(status, str) else None,
    )


def verify_webhook(
    payload: bytes,
    signature_header: str | None,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Verify a Paystack webhook signature and return the parsed event payload."""
    if not signature_header:
        raise PaystackProviderError("x-paystack-signature header is missing.")
    resolved_settings = settings or get_settings()
    expected = hmac.new(
        _webhook_secret(resolved_settings).encode(),
        payload,
        hashlib.sha512,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise PaystackProviderError("Paystack webhook signature verification failed.")
    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PaystackProviderError(
            "Paystack webhook payload is not valid JSON."
        ) from exc
    if not isinstance(event, dict):
        raise PaystackProviderError("Paystack webhook payload must be a JSON object.")
    return event
