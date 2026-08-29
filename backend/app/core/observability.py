"""Error tracking wiring for the API, workers, and Beat.

Initialises the Sentry SDK when ``SENTRY_DSN`` is set and stays completely
inert when it is not, so local development and the test suite are unaffected.

Three of the SDK's defaults are unsafe for this application and are turned off
explicitly here rather than left to a deployment to remember:

* ``max_request_body_size`` defaults to ``"medium"``, which transmits JSON
  request bodies. It is governed separately from ``send_default_pii``, so
  disabling PII does not disable it. Login and registration bodies carry
  plaintext passwords, TOTP enrollment carries the account password, and payout
  account creation carries Nigerian bank details. Pydantic's ``SecretStr`` does
  not help: the SDK reads the raw body off the ASGI scope before Pydantic ever
  parses it.
* ``include_local_variables`` defaults to ``True``, attaching every stack
  frame's locals. ``app/core/security.py`` returns decrypted TOTP seeds, payout
  provider account ids, connector tokens, and partner webhook secrets, and
  every caller holds that plaintext in a local. This path never passes through
  a log statement, so the logging discipline does not cover it.
* ``send_default_pii`` defaults to unset. Pinned to ``False`` so the intent is
  explicit and a future edit has to argue with a named value.

Two disclosures are kept deliberately. Full request URLs and query strings are
always transmitted and cannot be disabled, which is tolerable only because
access tokens are no longer accepted as query parameters. Source context — the
code lines surrounding each frame — is also retained: it carries no runtime
values, and removing it (``include_source_context=False``) would strip stack
traces of most of their diagnostic value. It does mean source lines reach a
third party, which is a disclosure decision rather than a leak.

Maps to: CLAUDE.md logging standards (CRITICAL severity routing).
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import sentry_sdk
from loguru import logger
from sentry_sdk.types import Event, Hint

from app.core.config import Settings

REDACTED = "[redacted]"

# Substring match against event keys. Deliberately broad: a false redaction
# costs one debugging session, a false negative ships a live credential.
_SENSITIVE_KEY_FRAGMENTS = (
    "account_number",
    "api_key",
    "authorization",
    "bank_code",
    "credential",
    "password",
    "secret",
    "token",
    "totp",
)

# Sink registration is tracked so that reconfiguring replaces the sink instead
# of stacking another one, which would duplicate every alert. `create_app()`
# runs more than once across a test session and can run again under a reloader.
_critical_sink_id: int | None = None


def _is_sensitive_key(key: str) -> bool:
    """Return whether an event key should have its value redacted."""
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _redact_mapping(values: dict[str, Any]) -> dict[str, Any]:
    """Replace sensitive values in one flat event mapping."""
    return {
        key: REDACTED if _is_sensitive_key(key) else value
        for key, value in values.items()
    }


def scrub_event(event: Event, hint: Hint) -> Event | None:
    """Strip request payloads and sensitive values from an outbound event.

    Runs as the SDK's ``before_send`` hook. Dropping the request body here is
    redundant with ``max_request_body_size="never"`` and intentionally so: it
    is the field that carries passwords and bank account numbers, and one
    defence for it is not enough.

    Args:
        event: The event the SDK is about to transmit.
        hint: SDK-supplied context about the event's origin. Unused.

    Returns:
        The event with sensitive fields removed, or None to drop it entirely.
    """
    del hint

    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = _redact_mapping(headers)

    extra = event.get("extra")
    if isinstance(extra, dict):
        event["extra"] = _redact_mapping(extra)

    tags = event.get("tags")
    if isinstance(tags, dict):
        event["tags"] = _redact_mapping(tags)

    return event


def _forward_critical(message: Any) -> None:
    """Forward one CRITICAL loguru record to Sentry as an event."""
    sentry_sdk.capture_message(message.record["message"], level="fatal")


def reset_error_tracking() -> None:
    """Remove the CRITICAL forwarding sink if one is registered.

    Tolerates an already-removed sink: ``configure_logging`` calls
    ``logger.remove()`` with no argument, which drops every sink including this
    one and leaves the recorded id stale. loguru raises on removing an id that
    no longer exists, and ``create_app()`` performs exactly that sequence.
    """
    global _critical_sink_id
    if _critical_sink_id is not None:
        with suppress(ValueError):
            logger.remove(_critical_sink_id)
        _critical_sink_id = None


def configure_error_tracking(settings: Settings) -> bool:
    """Initialise error tracking, or do nothing when no DSN is configured.

    Args:
        settings: Application settings carrying the DSN and sample rate.

    Returns:
        True when the SDK was initialised, False when it stayed inert.
    """
    # Blank counts as absent. `SENTRY_DSN=` in an env file parses to
    # SecretStr('') rather than None, and deploy tooling that writes empty
    # values for unset variables would otherwise initialise the SDK against an
    # empty DSN — failing in a deployed environment but never locally.
    dsn = settings.sentry_dsn.get_secret_value().strip() if settings.sentry_dsn else ""
    if not dsn:
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.environment,
        # See the module docstring: each of these three is a leaky default.
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        before_send=scrub_event,
        traces_sample_rate=settings.sentry_traces_sample_rate,
    )

    # loguru never reaches stdlib `logging`, which is the only thing Sentry's
    # LoggingIntegration hooks, so without this sink the SDK would see none of
    # this application's logs. CLAUDE.md reserves CRITICAL for escrow_mismatch
    # and double_charge_detected — exactly the events worth paging a human for.
    global _critical_sink_id
    reset_error_tracking()
    _critical_sink_id = logger.add(_forward_critical, level="CRITICAL")
    return True
