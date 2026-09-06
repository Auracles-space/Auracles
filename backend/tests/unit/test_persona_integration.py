"""Tests for the Persona identity-verification provider adapter.

Covers inquiry creation (create + one-time-link) and webhook signature
verification. Persona is the IDV provider that replaces admin-manual KYC.

Maps to: identity verification design (2026-06-24), build slice 1.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from app.core.config import Settings
from app.integrations.persona import (
    PersonaProviderError,
    build_hosted_inquiry_url,
    create_inquiry,
    fetch_inquiry,
    verify_webhook,
)

PERSONA_SETTINGS = Settings(
    PERSONA_API_KEY="persona_test_key",
    PERSONA_WEBHOOK_SECRET="wbhsec_test",
    PERSONA_INQUIRY_TEMPLATE_ID="itmpl_test",
    PERSONA_REDIRECT_URL="https://auracles.space/settings/kyc",
)


@pytest.mark.asyncio
@respx.mock
async def test_create_inquiry_returns_inquiry_id_and_hosted_url() -> None:
    """Inquiry creation tags the user reference and returns a one-time link."""
    create_route = respx.post("https://api.withpersona.com/api/v1/inquiries").mock(
        return_value=httpx.Response(
            201,
            json={"data": {"id": "inq_123", "type": "inquiry", "attributes": {}}},
        )
    )
    link_route = respx.post(
        "https://api.withpersona.com/api/v1/inquiries/inq_123/generate-one-time-link"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "meta": {
                    "one-time-link": "https://withpersona.com/verify?inquiry-id=inq_123&one-time-link-token=tok"
                }
            },
        )
    )

    result = await create_inquiry(
        reference_id="11111111-1111-1111-1111-111111111111",
        settings=PERSONA_SETTINGS,
    )

    assert result.inquiry_id == "inq_123"
    assert result.hosted_url.startswith(
        "https://withpersona.com/verify?inquiry-id=inq_123"
    )
    # The configured completion URL is appended so Persona returns the user to
    # the app after the hosted flow finishes.
    encoded_redirect = "redirect-uri=https%3A%2F%2Fauracles.space%2Fsettings%2Fkyc"
    assert encoded_redirect in result.hosted_url

    create_request = create_route.calls.last.request
    assert create_request.headers["Authorization"] == "Bearer persona_test_key"
    assert json.loads(create_request.content) == {
        "data": {
            "attributes": {
                "inquiry-template-id": "itmpl_test",
                "reference-id": "11111111-1111-1111-1111-111111111111",
            }
        }
    }
    assert link_route.called


@pytest.mark.asyncio
@respx.mock
async def test_create_inquiry_raises_on_provider_error() -> None:
    """A non-2xx Persona response surfaces as a typed provider error."""
    respx.post("https://api.withpersona.com/api/v1/inquiries").mock(
        return_value=httpx.Response(422, json={"errors": [{"title": "bad template"}]})
    )

    with pytest.raises(PersonaProviderError):
        await create_inquiry(
            reference_id="11111111-1111-1111-1111-111111111111",
            settings=PERSONA_SETTINGS,
        )


@pytest.mark.asyncio
@respx.mock
async def test_fetch_inquiry_returns_status_and_reference() -> None:
    """Fetching an inquiry returns its authoritative status and reference id.

    Backs the on-return sync path: the app reads the verdict directly from
    Persona (server-to-server) instead of waiting for the inbound webhook.
    """
    route = respx.get(
        "https://api.withpersona.com/api/v1/inquiries/inq_123"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "id": "inq_123",
                    "type": "inquiry",
                    "attributes": {
                        "status": "approved",
                        "reference-id": "11111111-1111-1111-1111-111111111111",
                    },
                }
            },
        )
    )

    result = await fetch_inquiry(
        inquiry_id="inq_123",
        settings=PERSONA_SETTINGS,
    )

    assert result.inquiry_id == "inq_123"
    assert result.status == "approved"
    assert result.reference_id == "11111111-1111-1111-1111-111111111111"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer persona_test_key"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_inquiry_raises_on_provider_error() -> None:
    """A non-2xx inquiry read surfaces as a typed provider error."""
    respx.get("https://api.withpersona.com/api/v1/inquiries/inq_missing").mock(
        return_value=httpx.Response(404, json={"errors": [{"title": "not found"}]})
    )

    with pytest.raises(PersonaProviderError):
        await fetch_inquiry(inquiry_id="inq_missing", settings=PERSONA_SETTINGS)


def _persona_signature(secret: str, timestamp: str, payload: bytes) -> str:
    """Build a Persona-Signature header value for the signed payload."""
    digest = hmac.new(
        secret.encode(),
        f"{timestamp}.{payload.decode()}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def test_verify_webhook_accepts_valid_signature_and_rejects_tampering() -> None:
    """Persona webhook verification uses HMAC-SHA256 over `t.body`."""
    payload = json.dumps(
        {"data": {"attributes": {"name": "inquiry.completed"}}},
        separators=(",", ":"),
    ).encode()
    header = _persona_signature("wbhsec_test", "1718000000", payload)

    event = verify_webhook(payload, header, settings=PERSONA_SETTINGS)

    assert event["data"]["attributes"]["name"] == "inquiry.completed"

    with pytest.raises(PersonaProviderError):
        verify_webhook(payload, "t=1718000000,v1=deadbeef", settings=PERSONA_SETTINGS)

    with pytest.raises(PersonaProviderError):
        verify_webhook(payload, None, settings=PERSONA_SETTINGS)


HOSTED_SETTINGS = Settings(
    PERSONA_API_KEY="persona_test_key",
    PERSONA_WEBHOOK_SECRET="wbhsec_test",
    PERSONA_INQUIRY_TEMPLATE_ID="itmpl_test",
    PERSONA_ENVIRONMENT_ID="env_test",
    PERSONA_REDIRECT_URL="https://auracles.space/settings/kyc",
)


def test_build_hosted_inquiry_url_carries_template_environment_and_reference() -> None:
    """The hosted link addresses the template and tags the user reference.

    Hosted flow is how inquiries are created: Persona mints the inquiry when
    the user lands, so no API call and no ``inquiries.create.api`` permission
    is involved. The reference id is what later maps the webhook back to the
    user, since the inquiry id does not exist until the user arrives.
    """
    url = build_hosted_inquiry_url(
        reference_id="11111111-1111-1111-1111-111111111111",
        settings=HOSTED_SETTINGS,
    )

    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "inquiry.withpersona.com"
    assert parsed.path == "/verify"

    query = parse_qs(parsed.query)
    assert query["inquiry-template-id"] == ["itmpl_test"]
    assert query["environment-id"] == ["env_test"]
    assert query["reference-id"] == ["11111111-1111-1111-1111-111111111111"]
    assert query["redirect-uri"] == ["https://auracles.space/settings/kyc"]


def test_build_hosted_inquiry_url_requires_environment_id() -> None:
    """A missing environment id fails loudly rather than defaulting.

    Persona resolves Sandbox vs Production from this parameter. Omitting it
    would silently send staging testers into the production environment.
    """
    settings = Settings(
        PERSONA_API_KEY="persona_test_key",
        PERSONA_WEBHOOK_SECRET="wbhsec_test",
        PERSONA_INQUIRY_TEMPLATE_ID="itmpl_test",
    )

    with pytest.raises(PersonaProviderError):
        build_hosted_inquiry_url(
            reference_id="11111111-1111-1111-1111-111111111111",
            settings=settings,
        )


def test_build_hosted_inquiry_url_omits_redirect_when_unset() -> None:
    """No configured redirect means no redirect-uri parameter, not an empty one.

    ``PERSONA_REDIRECT_URL`` is passed as None explicitly: a developer's local
    ``.env`` supplies one, and inheriting it would make this assertion pass or
    fail depending on whose machine ran it.
    """
    settings = Settings(
        PERSONA_API_KEY="persona_test_key",
        PERSONA_WEBHOOK_SECRET="wbhsec_test",
        PERSONA_INQUIRY_TEMPLATE_ID="itmpl_test",
        PERSONA_ENVIRONMENT_ID="env_test",
        PERSONA_REDIRECT_URL=None,
    )

    url = build_hosted_inquiry_url(
        reference_id="11111111-1111-1111-1111-111111111111",
        settings=settings,
    )

    assert "redirect-uri" not in parse_qs(urlparse(url).query)
