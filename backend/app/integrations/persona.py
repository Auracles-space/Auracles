"""Persona HTTP adapter for identity-verification inquiries and webhooks.

Persona is the third-party IDV provider that replaces admin-manual KYC. We
create an inquiry tagged with the user's id (reference-id), hand the user a
one-time hosted link, and react to the inquiry decision via signed webhooks.
We never store the user's raw documents — Persona is the custodian.

Persona REST API: https://docs.withpersona.com/reference (API v1).

NOTE: exact request/response field names are pinned by the unit tests and must
be confirmed against the Persona sandbox before production (see design risks).

Maps to: identity verification design (2026-06-24), build slice 1.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import Settings, get_settings

PERSONA_API_BASE_URL = "https://api.withpersona.com/api/v1"
# Hosted flow lives on the account's inquiry subdomain, not the API host.
# `inquiry` is Persona's default; change this only if the org sets a custom one.
PERSONA_HOSTED_FLOW_URL = "https://inquiry.withpersona.com/verify"
PERSONA_API_VERSION = "2023-01-05"
PERSONA_TIMEOUT_SECONDS = 15.0


class PersonaProviderError(RuntimeError):
    """Raised when Persona configuration, requests, or signatures are invalid."""


@dataclass(frozen=True)
class PersonaInquiry:
    """Normalized Persona inquiry result.

    Attributes:
        inquiry_id: Persona inquiry id (``inq_...``); maps webhooks back to us.
        hosted_url: One-time link the user opens to complete verification.
    """

    inquiry_id: str
    hosted_url: str


@dataclass(frozen=True)
class PersonaInquiryStatus:
    """Authoritative status of a Persona inquiry read server-to-server.

    Attributes:
        inquiry_id: Persona inquiry id (``inq_...``).
        status: Current inquiry status (``approved``/``declined``/``pending``…).
        reference_id: The ``reference-id`` tagged on the inquiry (our user id),
            used to confirm the caller owns the inquiry before applying it.
    """

    inquiry_id: str
    status: str
    reference_id: str | None


def _require_api_key(settings: Settings) -> str:
    """Return the configured Persona API key or raise a provider error."""
    if settings.persona_api_key is None:
        raise PersonaProviderError("PERSONA_API_KEY is not configured.")
    return settings.persona_api_key.get_secret_value()


def _require_template_id(settings: Settings) -> str:
    """Return the configured Persona inquiry template id or raise."""
    if settings.persona_inquiry_template_id is None:
        raise PersonaProviderError("PERSONA_INQUIRY_TEMPLATE_ID is not configured.")
    return settings.persona_inquiry_template_id


def _webhook_secret(settings: Settings) -> str:
    """Return the Persona webhook signing secret or raise a provider error."""
    if settings.persona_webhook_secret is None:
        raise PersonaProviderError("PERSONA_WEBHOOK_SECRET is not configured.")
    return settings.persona_webhook_secret.get_secret_value()


async def _post_json(
    path: str,
    body: dict[str, Any] | None,
    *,
    settings: Settings,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """POST JSON to Persona and return the parsed response object."""
    headers = {
        "Authorization": f"Bearer {_require_api_key(settings)}",
        "Persona-Version": PERSONA_API_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        response = await client.post(
            f"{PERSONA_API_BASE_URL}{path}",
            json=body,
            headers=headers,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PersonaProviderError(
                f"Persona returned {response.status_code}."
            ) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise PersonaProviderError("Persona response is not a JSON object.")
        return payload
    except httpx.HTTPError as exc:
        raise PersonaProviderError("Persona request failed.") from exc


async def _get_json(
    path: str,
    *,
    settings: Settings,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """GET JSON from Persona and return the parsed response object."""
    headers = {
        "Authorization": f"Bearer {_require_api_key(settings)}",
        "Persona-Version": PERSONA_API_VERSION,
        "Accept": "application/json",
    }
    try:
        response = await client.get(
            f"{PERSONA_API_BASE_URL}{path}",
            headers=headers,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PersonaProviderError(
                f"Persona returned {response.status_code}."
            ) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise PersonaProviderError("Persona response is not a JSON object.")
        return payload
    except httpx.HTTPError as exc:
        raise PersonaProviderError("Persona request failed.") from exc


async def fetch_inquiry(
    *,
    inquiry_id: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> PersonaInquiryStatus:
    """Read an inquiry's authoritative status directly from Persona.

    Backs the on-return sync path (identity verification design, 2026-06-24):
    when the user returns from the hosted flow, the app pulls the verdict
    server-to-server rather than waiting for the asynchronous webhook. The
    ``reference-id`` is returned so the caller can confirm inquiry ownership
    before applying any decision.

    Args:
        inquiry_id: Persona inquiry id (``inq_...``) to read.
        settings: Optional settings override (defaults to process settings).
        client: Optional injected httpx client (defaults to a new one).

    Returns:
        The inquiry id, current status, and tagged reference id.

    Raises:
        PersonaProviderError: On missing config or any provider failure.
    """
    resolved_settings = settings or get_settings()
    owns_client = client is None
    resolved_client = client or httpx.AsyncClient(timeout=PERSONA_TIMEOUT_SECONDS)
    try:
        payload = await _get_json(
            f"/inquiries/{inquiry_id}",
            settings=resolved_settings,
            client=resolved_client,
        )
        data = payload.get("data")
        attributes = data.get("attributes") if isinstance(data, dict) else None
        if not isinstance(attributes, dict):
            raise PersonaProviderError("Persona inquiry response missing attributes.")
        status = attributes.get("status")
        if not isinstance(status, str) or not status:
            raise PersonaProviderError("Persona inquiry response missing status.")
        reference_id = attributes.get("reference-id")
        return PersonaInquiryStatus(
            inquiry_id=inquiry_id,
            status=status,
            reference_id=reference_id if isinstance(reference_id, str) else None,
        )
    finally:
        if owns_client:
            await resolved_client.aclose()


def _append_redirect(hosted_url: str, redirect_url: str | None) -> str:
    """Append a ``redirect-uri`` query param to a hosted-flow link.

    Persona returns the user to this URL (with ``inquiry-id``/``reference-id``)
    once the hosted flow completes. Without it, the user lands on Persona's own
    completion screen. No-op when no redirect URL is configured.
    """
    if not redirect_url:
        return hosted_url
    separator = "&" if "?" in hosted_url else "?"
    return f"{hosted_url}{separator}{urlencode({'redirect-uri': redirect_url})}"


def _require_environment_id(settings: Settings) -> str:
    """Return the configured Persona environment id or raise.

    Deliberately has no default. The environment id is what selects Sandbox
    versus Production on a hosted link, so falling back to either one would
    quietly send staging testers into the wrong environment — and in the
    Production direction that means real identity checks against real people.
    """
    if settings.persona_environment_id is None:
        raise PersonaProviderError("PERSONA_ENVIRONMENT_ID is not configured.")
    return settings.persona_environment_id


def build_hosted_inquiry_url(
    *,
    reference_id: str,
    settings: Settings | None = None,
) -> str:
    """Build the hosted-flow link that starts identity verification.

    Persona mints the inquiry when the user lands on this URL, so nothing is
    called server-side and no API-key permission is involved. This is why the
    app uses it in preference to ``create_inquiry``: the Auracles Persona
    environment does not have ``inquiries.create.api`` enabled, and a key
    cannot grant it — three separate sandbox keys were refused identically
    (2026-09-06).

    The consequence to know about: the inquiry id does not exist yet, so the
    ``IdentityVerification`` row is written with a null ``inquiry_id`` and is
    matched later by ``reference_id`` — see ``_apply_persona_decision``.

    Args:
        reference_id: Our user id, tagged on the inquiry so the webhook and the
            on-return sync can map Persona's verdict back to the user.
        settings: Optional settings override (defaults to process settings).

    Returns:
        Absolute hosted-flow URL for the user's browser.

    Raises:
        PersonaProviderError: If the template id or environment id is missing.
    """
    resolved = settings or get_settings()
    params = {
        "inquiry-template-id": _require_template_id(resolved),
        "environment-id": _require_environment_id(resolved),
        "reference-id": reference_id,
    }
    if resolved.persona_redirect_url:
        params["redirect-uri"] = resolved.persona_redirect_url
    return f"{PERSONA_HOSTED_FLOW_URL}?{urlencode(params)}"


def _extract_one_time_link(payload: dict[str, Any]) -> str:
    """Pull the one-time link from a generate-one-time-link response.

    Persona returns the link under ``meta``; we also accept it on the inquiry
    attributes to stay resilient to minor API-shape differences.
    """
    meta = payload.get("meta")
    if isinstance(meta, dict):
        link = meta.get("one-time-link")
        if isinstance(link, str) and link:
            return link
    data = payload.get("data")
    if isinstance(data, dict):
        attributes = data.get("attributes")
        if isinstance(attributes, dict):
            link = attributes.get("one-time-link")
            if isinstance(link, str) and link:
                return link
    raise PersonaProviderError("Persona response missing one-time link.")


async def create_inquiry(
    *,
    reference_id: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> PersonaInquiry:
    """Create a Persona inquiry for a user and return its id + hosted link.

    Tags the inquiry with ``reference-id`` (our user id) so the webhook can map
    the decision back to the user, then generates a one-time link for the user
    to complete the flow.

    Args:
        reference_id: Our user id, stored on the inquiry as ``reference-id``.
        settings: Optional settings override (defaults to process settings).
        client: Optional injected httpx client (defaults to a new one).

    Returns:
        PersonaInquiry with the inquiry id and one-time hosted URL.

    Raises:
        PersonaProviderError: On missing config or any provider failure.
    """
    resolved_settings = settings or get_settings()
    owns_client = client is None
    resolved_client = client or httpx.AsyncClient(timeout=PERSONA_TIMEOUT_SECONDS)
    try:
        created = await _post_json(
            "/inquiries",
            {
                "data": {
                    "attributes": {
                        "inquiry-template-id": _require_template_id(resolved_settings),
                        "reference-id": reference_id,
                    }
                }
            },
            settings=resolved_settings,
            client=resolved_client,
        )
        data = created.get("data")
        inquiry_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(inquiry_id, str) or not inquiry_id:
            raise PersonaProviderError("Persona inquiry response missing id.")

        link_payload = await _post_json(
            f"/inquiries/{inquiry_id}/generate-one-time-link",
            None,
            settings=resolved_settings,
            client=resolved_client,
        )
        return PersonaInquiry(
            inquiry_id=inquiry_id,
            hosted_url=_append_redirect(
                _extract_one_time_link(link_payload),
                resolved_settings.persona_redirect_url,
            ),
        )
    finally:
        if owns_client:
            await resolved_client.aclose()


def _parse_signature_header(signature_header: str) -> tuple[str, list[str]]:
    """Return ``(timestamp, [v1 digests])`` from a Persona-Signature header.

    Header format: ``t=<unix>,v1=<hex>`` (multiple ``v1=`` values may appear
    space-separated while a webhook secret is being rotated).
    """
    timestamp: str | None = None
    digests: list[str] = []
    for part in signature_header.replace(" ", ",").split(","):
        key, _, value = part.partition("=")
        if key == "t" and value:
            timestamp = value
        elif key == "v1" and value:
            digests.append(value)
    if timestamp is None or not digests:
        raise PersonaProviderError("Persona-Signature header is malformed.")
    return timestamp, digests


def verify_webhook(
    payload: bytes,
    signature_header: str | None,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Verify a Persona webhook signature and return the parsed event payload.

    Persona signs ``"{timestamp}.{raw_body}"`` with HMAC-SHA256 using the
    webhook secret. Verification runs before any JSON parsing.

    Args:
        payload: Raw request body bytes.
        signature_header: The ``Persona-Signature`` header value.
        settings: Optional settings override.

    Returns:
        The parsed event payload as a dict.

    Raises:
        PersonaProviderError: On missing/invalid signature or non-JSON body.
    """
    if not signature_header:
        raise PersonaProviderError("Persona-Signature header is missing.")
    resolved_settings = settings or get_settings()
    timestamp, digests = _parse_signature_header(signature_header)
    expected = hmac.new(
        _webhook_secret(resolved_settings).encode(),
        f"{timestamp}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    if not any(hmac.compare_digest(expected, digest) for digest in digests):
        raise PersonaProviderError("Persona webhook signature verification failed.")
    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PersonaProviderError(
            "Persona webhook payload is not valid JSON."
        ) from exc
    if not isinstance(event, dict):
        raise PersonaProviderError("Persona webhook payload must be a JSON object.")
    return event
