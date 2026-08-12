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
class PaystackTransferRecipient:
    """Normalized Paystack transfer recipient result.

    Attributes:
        recipient_code: The `RCP_...` code every later transfer is addressed to.
        account_name: Name the bank holds for the account. Shown back to the
            Contributor so a mistyped account number is caught before money
            moves, since Paystack resolves it during recipient creation.
    """

    recipient_code: str
    account_name: str | None


@dataclass(frozen=True)
class PaystackBank:
    """A bank a Nigerian payout account can be held at."""

    name: str
    code: str


@dataclass(frozen=True)
class PaystackTransfer:
    """Normalized Paystack transfer result."""

    id: str
    status: str | None
    transfer_code: str | None = None


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


async def _get_json(
    path: str,
    params: Mapping[str, str],
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> Any:
    """GET from Paystack and return the nested data payload.

    Unlike `_post_json` the shape is not narrowed to a dict: Paystack's
    collection endpoints (`/bank`) return a list under the same `data` key.

    Args:
        path: API path beginning with a slash.
        params: Query string parameters.
        settings: Settings override, defaulting to the app settings.
        client: HTTP client override, primarily for tests.

    Returns:
        The value of the response's `data` key.

    Raises:
        PaystackProviderError: On transport failure, a non-2xx status, or a
            response Paystack itself marked unsuccessful.
    """
    resolved_settings = settings or get_settings()
    headers = {"Authorization": f"Bearer {_require_secret_key(resolved_settings)}"}

    owns_client = client is None
    resolved_client = client or httpx.AsyncClient(timeout=PAYSTACK_TIMEOUT_SECONDS)
    try:
        response = await resolved_client.get(
            f"{PAYSTACK_API_BASE_URL}{path}",
            params=dict(params),
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
        if "data" not in payload:
            raise PaystackProviderError("Paystack response missing data.")
        return payload["data"]
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


async def fetch_refund(
    *,
    refund_id: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> PaystackRefund:
    """Fetch one refund's current status from Paystack.

    Used by reconciliation when a refund's settlement webhook never arrived.
    Paystack's List Refunds endpoint cannot filter by transaction, so the
    refund's own id — stored on the ledger event at request time — is the only
    way to ask about a specific refund.

    Args:
        refund_id: Paystack's identifier for the refund.
        settings: Optional settings override.
        client: Optional HTTP client, for reuse across a batch.

    Returns:
        The refund with its current provider status.

    Raises:
        PaystackProviderError: If the call fails or the response has no status.
    """
    data = await _get_json(
        f"/refund/{refund_id}",
        {},
        settings=settings,
        client=client,
    )
    if not isinstance(data, dict):
        raise PaystackProviderError("Paystack refund response was not an object.")
    raw_id = data.get("id")
    refund_status = data.get("status")
    if not isinstance(refund_status, str):
        raise PaystackProviderError("Paystack refund response missing status.")
    return PaystackRefund(
        id=str(raw_id) if isinstance(raw_id, int | str) else refund_id,
        status=refund_status,
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


async def create_transfer_recipient(
    *,
    name: str,
    account_number: str,
    bank_code: str,
    currency: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> PaystackTransferRecipient:
    """Register a Nigerian bank account as a payout destination.

    Paystack resolves the account number against the bank during creation, so a
    successful response doubles as verification that the account exists — there
    is no separate confirmation step to wait on, unlike Stripe Connect's hosted
    onboarding.

    Args:
        name: Account holder name to register the recipient under.
        account_number: NUBAN account number.
        bank_code: Paystack bank code, from `list_banks`.
        currency: Settlement currency for the recipient.
        settings: Settings override, defaulting to the app settings.
        client: HTTP client override, primarily for tests.

    Returns:
        The recipient code and the bank-confirmed account name.

    Raises:
        PaystackProviderError: If Paystack rejects the account or the response
            carries no recipient code to address later transfers to.
    """
    data = await _post_json(
        "/transferrecipient",
        {
            "type": "nuban",
            "name": name,
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": currency.upper(),
        },
        settings=settings,
        client=client,
    )
    recipient_code = data.get("recipient_code")
    if not isinstance(recipient_code, str):
        raise PaystackProviderError(
            "Paystack transfer recipient response missing recipient code."
        )
    details = data.get("details")
    account_name = details.get("account_name") if isinstance(details, dict) else None
    return PaystackTransferRecipient(
        recipient_code=recipient_code,
        account_name=account_name if isinstance(account_name, str) else None,
    )


async def list_banks(
    *,
    country: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[PaystackBank]:
    """List banks a payout account can be held at, as Paystack reports them.

    Never hardcode this list. Bank codes change and new institutions appear, so
    a stale local copy either rejects a valid account or addresses money to the
    wrong institution.

    Entries missing a name or code are skipped rather than failing the call: one
    unusable row must not deny the Contributor the entire list.

    Args:
        country: Paystack country slug, e.g. `nigeria`.
        settings: Settings override, defaulting to the app settings.
        client: HTTP client override, primarily for tests.

    Returns:
        Banks with both a display name and a usable code.

    Raises:
        PaystackProviderError: On transport failure or an unexpected shape.
    """
    data = await _get_json(
        "/bank",
        {"country": country},
        settings=settings,
        client=client,
    )
    if not isinstance(data, list):
        raise PaystackProviderError("Paystack bank list response is not a list.")
    banks: list[PaystackBank] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        code = entry.get("code")
        if isinstance(name, str) and isinstance(code, str | int):
            banks.append(PaystackBank(name=name, code=str(code)))
    return banks


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
    transfer_code = data.get("transfer_code")
    if not isinstance(raw_id, int | str):
        raise PaystackProviderError("Paystack transfer response missing id.")
    return PaystackTransfer(
        id=str(raw_id),
        status=status if isinstance(status, str) else None,
        transfer_code=transfer_code if isinstance(transfer_code, str) else None,
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
