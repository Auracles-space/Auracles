"""Stripe HTTP adapter for payments, refunds, Connect, and webhooks.

The adapter intentionally exposes small Auracles-owned return types instead of
leaking Stripe response shapes into service code. Later financial service
slices can depend on these helpers without knowing Stripe's form encoding.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.integrations.amounts import MoneyAmountError, to_minor_units

STRIPE_API_BASE_URL = "https://api.stripe.com/v1"
STRIPE_TIMEOUT_SECONDS = 15.0
STRIPE_SIGNATURE_TOLERANCE_SECONDS = 300


class StripeProviderError(RuntimeError):
    """Raised when Stripe configuration, requests, or signatures are invalid."""


@dataclass(frozen=True)
class StripeCustomer:
    """Normalized Stripe Customer creation result."""

    id: str


@dataclass(frozen=True)
class StripePaymentIntent:
    """Normalized Stripe PaymentIntent result returned to checkout services."""

    id: str
    client_secret: str


@dataclass(frozen=True)
class StripeSetupIntent:
    """Normalized Stripe SetupIntent result returned to card setup services."""

    id: str
    client_secret: str


@dataclass(frozen=True)
class StripePaymentMethod:
    """Safe Stripe PaymentMethod metadata without PAN or CVC data."""

    id: str
    type: str
    brand: str | None
    last4: str | None
    exp_month: int | None
    exp_year: int | None


@dataclass(frozen=True)
class StripeRefund:
    """Normalized Stripe refund result."""

    id: str
    status: str


@dataclass(frozen=True)
class StripeAccount:
    """Normalized Stripe Connect account result."""

    id: str


@dataclass(frozen=True)
class StripeAccountLink:
    """Normalized Stripe Connect onboarding link result."""

    url: str


@dataclass(frozen=True)
class StripeTransfer:
    """Normalized Stripe transfer result."""

    id: str
    status: str | None


def _require_secret_key(settings: Settings) -> str:
    """Return the configured Stripe API key or raise a provider error."""
    if settings.stripe_secret_key is None:
        raise StripeProviderError("STRIPE_SECRET_KEY is not configured.")
    return settings.stripe_secret_key.get_secret_value()


def _require_webhook_secret(settings: Settings) -> str:
    """Return the configured Stripe webhook secret or raise a provider error."""
    if settings.stripe_webhook_secret is None:
        raise StripeProviderError("STRIPE_WEBHOOK_SECRET is not configured.")
    return settings.stripe_webhook_secret.get_secret_value()


def _metadata_form(metadata: Mapping[str, str]) -> dict[str, str]:
    """Encode Stripe metadata into nested form keys."""
    return {f"metadata[{key}]": value for key, value in metadata.items()}


async def _post_form(
    path: str,
    form: Mapping[str, str | int],
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """POST a form-encoded request to Stripe and return JSON payload."""
    resolved_settings = settings or get_settings()
    headers = {"Authorization": f"Bearer {_require_secret_key(resolved_settings)}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    owns_client = client is None
    resolved_client = client or httpx.AsyncClient(timeout=STRIPE_TIMEOUT_SECONDS)
    try:
        response = await resolved_client.post(
            f"{STRIPE_API_BASE_URL}{path}",
            data=dict(form),
            headers=headers,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise StripeProviderError(
                f"Stripe returned {response.status_code}."
            ) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise StripeProviderError("Stripe returned malformed JSON.")
        return payload
    except httpx.HTTPError as exc:
        raise StripeProviderError("Stripe request failed.") from exc
    finally:
        if owns_client:
            await resolved_client.aclose()


async def _get_json(
    path: str,
    *,
    params: Mapping[str, str],
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """GET a Stripe resource and return its JSON object payload."""
    resolved_settings = settings or get_settings()
    headers = {"Authorization": f"Bearer {_require_secret_key(resolved_settings)}"}
    owns_client = client is None
    resolved_client = client or httpx.AsyncClient(timeout=STRIPE_TIMEOUT_SECONDS)
    try:
        response = await resolved_client.get(
            f"{STRIPE_API_BASE_URL}{path}",
            params=dict(params),
            headers=headers,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise StripeProviderError(
                f"Stripe returned {response.status_code}."
            ) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise StripeProviderError("Stripe returned malformed JSON.")
        return payload
    except httpx.HTTPError as exc:
        raise StripeProviderError("Stripe request failed.") from exc
    finally:
        if owns_client:
            await resolved_client.aclose()


async def create_customer(
    *,
    email: str,
    name: str | None = None,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
    idempotency_key: str | None = None,
) -> StripeCustomer:
    """Create a Stripe Customer and return its provider id."""
    form: dict[str, str] = {"email": email}
    if name:
        form["name"] = name
    payload = await _post_form(
        "/customers",
        form,
        settings=settings,
        client=client,
        idempotency_key=idempotency_key,
    )
    customer_id = payload.get("id")
    if not isinstance(customer_id, str):
        raise StripeProviderError("Stripe customer response missing id.")
    return StripeCustomer(id=customer_id)


async def create_payment_intent(
    *,
    customer_id: str,
    amount: Decimal,
    currency: str,
    metadata: Mapping[str, str],
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
    idempotency_key: str | None = None,
) -> StripePaymentIntent:
    """Create a Stripe PaymentIntent using integer minor units."""
    try:
        minor_units = to_minor_units(amount, currency)
    except MoneyAmountError as exc:
        raise StripeProviderError(str(exc)) from exc

    payload = await _post_form(
        "/payment_intents",
        {
            "amount": minor_units,
            "currency": currency.lower(),
            "customer": customer_id,
            "automatic_payment_methods[enabled]": "true",
            **_metadata_form(metadata),
        },
        settings=settings,
        client=client,
        idempotency_key=idempotency_key,
    )
    payment_intent_id = payload.get("id")
    client_secret = payload.get("client_secret")
    if not isinstance(payment_intent_id, str) or not isinstance(client_secret, str):
        raise StripeProviderError("Stripe PaymentIntent response missing fields.")
    return StripePaymentIntent(id=payment_intent_id, client_secret=client_secret)


async def create_setup_intent(
    *,
    customer_id: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> StripeSetupIntent:
    """Create a Stripe SetupIntent so Elements can attach a provider-held method."""
    payload = await _post_form(
        "/setup_intents",
        {
            "customer": customer_id,
            "usage": "off_session",
            "automatic_payment_methods[enabled]": "true",
        },
        settings=settings,
        client=client,
    )
    setup_intent_id = payload.get("id")
    client_secret = payload.get("client_secret")
    if not isinstance(setup_intent_id, str) or not isinstance(client_secret, str):
        raise StripeProviderError("Stripe SetupIntent response missing fields.")
    return StripeSetupIntent(id=setup_intent_id, client_secret=client_secret)


async def list_payment_methods(
    *,
    customer_id: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[StripePaymentMethod]:
    """List provider-held card metadata for a Stripe customer."""
    payload = await _get_json(
        "/payment_methods",
        params={"customer": customer_id, "type": "card"},
        settings=settings,
        client=client,
    )
    data = payload.get("data")
    if not isinstance(data, list):
        raise StripeProviderError("Stripe PaymentMethods response missing data.")

    payment_methods: list[StripePaymentMethod] = []
    for item in data:
        if not isinstance(item, dict):
            raise StripeProviderError("Stripe PaymentMethod item is malformed.")
        method_id = item.get("id")
        method_type = item.get("type")
        card = item.get("card")
        if not isinstance(method_id, str) or not isinstance(method_type, str):
            raise StripeProviderError("Stripe PaymentMethod response missing fields.")
        if not isinstance(card, dict):
            card = {}
        brand = card.get("brand")
        last4 = card.get("last4")
        exp_month = card.get("exp_month")
        exp_year = card.get("exp_year")
        payment_methods.append(
            StripePaymentMethod(
                id=method_id,
                type=method_type,
                brand=brand if isinstance(brand, str) else None,
                last4=last4 if isinstance(last4, str) else None,
                exp_month=exp_month if isinstance(exp_month, int) else None,
                exp_year=exp_year if isinstance(exp_year, int) else None,
            )
        )
    return payment_methods


async def detach_payment_method(
    *,
    payment_method_id: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Detach a Stripe PaymentMethod from its customer."""
    payload = await _post_form(
        f"/payment_methods/{payment_method_id}/detach",
        {},
        settings=settings,
        client=client,
    )
    detached_id = payload.get("id")
    if not isinstance(detached_id, str):
        raise StripeProviderError("Stripe detach response missing id.")
    return detached_id


async def create_refund(
    *,
    payment_intent_id: str,
    amount: Decimal,
    currency: str,
    idempotency_key: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> StripeRefund:
    """Create a Stripe refund for a PaymentIntent."""
    try:
        minor_units = to_minor_units(amount, currency)
    except MoneyAmountError as exc:
        raise StripeProviderError(str(exc)) from exc

    payload = await _post_form(
        "/refunds",
        {"payment_intent": payment_intent_id, "amount": minor_units},
        settings=settings,
        client=client,
        idempotency_key=idempotency_key,
    )
    refund_id = payload.get("id")
    status = payload.get("status")
    if not isinstance(refund_id, str) or not isinstance(status, str):
        raise StripeProviderError("Stripe refund response missing fields.")
    return StripeRefund(id=refund_id, status=status)


async def create_express_account(
    *,
    email: str,
    country: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> StripeAccount:
    """Create a Stripe Connect Express account for contributor onboarding."""
    payload = await _post_form(
        "/accounts",
        {"type": "express", "email": email, "country": country.upper()},
        settings=settings,
        client=client,
    )
    account_id = payload.get("id")
    if not isinstance(account_id, str):
        raise StripeProviderError("Stripe account response missing id.")
    return StripeAccount(id=account_id)


async def create_account_link(
    *,
    account_id: str,
    refresh_url: str,
    return_url: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> StripeAccountLink:
    """Create a Stripe Connect onboarding account link."""
    payload = await _post_form(
        "/account_links",
        {
            "account": account_id,
            "refresh_url": refresh_url,
            "return_url": return_url,
            "type": "account_onboarding",
        },
        settings=settings,
        client=client,
    )
    url = payload.get("url")
    if not isinstance(url, str):
        raise StripeProviderError("Stripe account link response missing url.")
    return StripeAccountLink(url=url)


async def create_transfer(
    *,
    amount: Decimal,
    currency: str,
    destination_account_id: str,
    metadata: Mapping[str, str],
    idempotency_key: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> StripeTransfer:
    """Create a Stripe transfer to a connected account."""
    try:
        minor_units = to_minor_units(amount, currency)
    except MoneyAmountError as exc:
        raise StripeProviderError(str(exc)) from exc

    payload = await _post_form(
        "/transfers",
        {
            "amount": minor_units,
            "currency": currency.lower(),
            "destination": destination_account_id,
            **_metadata_form(metadata),
        },
        settings=settings,
        client=client,
        idempotency_key=idempotency_key,
    )
    transfer_id = payload.get("id")
    status = payload.get("status")
    if not isinstance(transfer_id, str):
        raise StripeProviderError("Stripe transfer response missing id.")
    return StripeTransfer(
        id=transfer_id,
        status=status if isinstance(status, str) else None,
    )


def _parse_signature_header(header: str) -> tuple[int, list[str]]:
    """Extract Stripe timestamp and v1 signatures from a header."""
    values: dict[str, list[str]] = {}
    for item in header.split(","):
        key, _, value = item.partition("=")
        if key and value:
            values.setdefault(key, []).append(value)
    timestamps = values.get("t") or []
    signatures = values.get("v1") or []
    if not timestamps or not signatures:
        raise StripeProviderError("Stripe signature header is malformed.")
    try:
        timestamp = int(timestamps[0])
    except ValueError as exc:
        raise StripeProviderError("Stripe signature timestamp is malformed.") from exc
    return timestamp, signatures


def make_test_signature_header(
    payload: bytes,
    *,
    secret: str,
    timestamp: int,
) -> str:
    """Build a Stripe-like signature header for tests."""
    signed_payload = f"{timestamp}.{payload.decode()}".encode()
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def verify_webhook(
    payload: bytes,
    signature_header: str | None,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
    tolerance_seconds: int = STRIPE_SIGNATURE_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """Verify a Stripe webhook signature and return the parsed event payload."""
    if not signature_header:
        raise StripeProviderError("Stripe-Signature header is missing.")
    resolved_settings = settings or get_settings()
    secret_value = _require_webhook_secret(resolved_settings)
    timestamp, signatures = _parse_signature_header(signature_header)
    current_timestamp = int(now.timestamp() if now else time.time())
    if abs(current_timestamp - timestamp) > tolerance_seconds:
        raise StripeProviderError("Stripe signature timestamp is outside tolerance.")

    try:
        decoded_payload = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StripeProviderError("Stripe webhook payload is not valid UTF-8.") from exc
    signed_payload = f"{timestamp}.{decoded_payload}".encode()

    # Support multiple secrets for concurrent standard and connect webhook endpoints
    secrets = [s.strip() for s in secret_value.split(",") if s.strip()]
    verified = False
    for secret in secrets:
        expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        if any(hmac.compare_digest(expected, candidate) for candidate in signatures):
            verified = True
            break

    if not verified:
        raise StripeProviderError("Stripe webhook signature verification failed.")

    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise StripeProviderError("Stripe webhook payload is not valid JSON.") from exc
    if not isinstance(event, dict):
        raise StripeProviderError("Stripe webhook payload must be a JSON object.")
    return event
