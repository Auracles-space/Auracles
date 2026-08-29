"""Error-tracking wiring and its data-protection guarantees.

The Sentry SDK's defaults are not safe for this application: it transmits JSON
request bodies and every stack frame's local variables unless told otherwise.
Login and registration bodies carry plaintext passwords, payout-account bodies
carry Nigerian bank details, and `app/core/security.py` returns decrypted TOTP
seeds and payout account ids into caller locals. These tests pin the options
that turn all of that off, so a later edit cannot quietly re-enable them.
"""

from __future__ import annotations

from typing import Any

import pytest
from loguru import logger

from app.core import observability
from app.core.config import Settings
from app.core.logging import configure_logging


def _settings(**overrides: object) -> Settings:
    """Build a Settings instance for observability tests."""
    return Settings(
        DATABASE_URL="postgresql+asyncpg://user:pw@localhost:5432/auracles",
        SECRET_KEY="x" * 32,
        **overrides,  # type: ignore[arg-type]
    )


@pytest.fixture(autouse=True)
def _reset_sentry_sink() -> Any:
    """Drop any loguru sink a test registered, so sinks do not leak."""
    yield
    observability.reset_error_tracking()


def test_error_tracking_stays_inert_without_a_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No DSN means the SDK is never initialised at all.

    Local development and the test suite run without one, and initialising
    against an unset DSN would either error or silently buffer events.
    """
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        observability.sentry_sdk,
        "init",
        lambda **kwargs: calls.append(kwargs),
    )

    enabled = observability.configure_error_tracking(_settings())

    assert enabled is False
    assert calls == []


@pytest.mark.parametrize("blank_dsn", ["", "   "])
def test_error_tracking_treats_a_blank_dsn_as_absent(
    monkeypatch: pytest.MonkeyPatch,
    blank_dsn: str,
) -> None:
    """An empty or whitespace DSN is the same as no DSN.

    ``SENTRY_DSN=`` in an env file parses to ``SecretStr('')`` rather than
    None, so a bare `is None` check would sail past and initialise the SDK
    against an empty DSN. Deploy tooling that sets empty values for unset
    variables would hit this in production, not locally.
    """
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        observability.sentry_sdk,
        "init",
        lambda **kwargs: calls.append(kwargs),
    )

    enabled = observability.configure_error_tracking(_settings(SENTRY_DSN=blank_dsn))

    assert enabled is False
    assert calls == []


def test_error_tracking_disables_every_default_that_would_leak_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The three leaky SDK defaults are explicitly turned off.

    ``max_request_body_size`` is the one that is easy to miss: request bodies
    are sent by default and are *not* governed by ``send_default_pii``, so
    leaving it alone would transmit plaintext passwords from the login route.
    """
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        observability.sentry_sdk,
        "init",
        lambda **kwargs: captured.update(kwargs),
    )

    enabled = observability.configure_error_tracking(
        _settings(SENTRY_DSN="https://public@example.ingest.sentry.io/1")
    )

    assert enabled is True
    assert captured["send_default_pii"] is False
    assert captured["include_local_variables"] is False
    assert captured["max_request_body_size"] == "never"
    assert captured["before_send"] is not None


def test_error_tracking_does_not_sample_traces_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Performance tracing is off unless asked for.

    Sentry bills by event volume, so tracing every request would burn the
    quota that error reporting actually needs.
    """
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        observability.sentry_sdk,
        "init",
        lambda **kwargs: captured.update(kwargs),
    )

    observability.configure_error_tracking(
        _settings(SENTRY_DSN="https://public@example.ingest.sentry.io/1")
    )

    assert captured["traces_sample_rate"] == 0.0


def test_scrubber_drops_a_request_body_that_reached_the_event() -> None:
    """Any request body on an outbound event is removed.

    Redundant with ``max_request_body_size="never"`` and deliberately so: this
    is the field that carries passwords and bank account numbers, and one
    defence for it is not enough.
    """
    event = {
        "request": {
            "url": "https://api.auracles.space/v1/auth/login",
            "data": {"email": "user@auracles.space", "password": "hunter2"},
            "cookies": {"refresh": "secret"},
        }
    }

    scrubbed = observability.scrub_event(event, {})

    assert scrubbed is not None
    assert "data" not in scrubbed["request"]
    assert "cookies" not in scrubbed["request"]
    assert scrubbed["request"]["url"] == "https://api.auracles.space/v1/auth/login"


def test_scrubber_redacts_sensitive_values_carried_in_extra() -> None:
    """Sensitive keys attached to an event are replaced, not passed through."""
    event = {
        "extra": {
            "framework_id": "abc-123",
            "totp_secret": "JBSWY3DPEHPK3PXP",
            "account_number": "0123456789",
            "authorization": "Bearer xyz",
        }
    }

    scrubbed = observability.scrub_event(event, {})

    assert scrubbed is not None
    assert scrubbed["extra"]["framework_id"] == "abc-123"
    assert scrubbed["extra"]["totp_secret"] == observability.REDACTED
    assert scrubbed["extra"]["account_number"] == observability.REDACTED
    assert scrubbed["extra"]["authorization"] == observability.REDACTED


def test_critical_logs_are_forwarded_to_sentry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CRITICAL loguru records raise a Sentry event.

    loguru never reaches stdlib ``logging``, which is the only thing Sentry's
    logging integration hooks, so without an explicit sink the SDK would see
    none of this application's logs. CLAUDE.md reserves CRITICAL for
    escrow_mismatch and double_charge_detected — the events most worth paging
    a human for.
    """
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        observability.sentry_sdk,
        "capture_message",
        lambda message, level="error": captured.append((message, level)),
    )
    monkeypatch.setattr(
        observability.sentry_sdk,
        "init",
        lambda **kwargs: None,
    )
    observability.configure_error_tracking(
        _settings(SENTRY_DSN="https://public@example.ingest.sentry.io/1")
    )

    logger.bind(module="financials", action="release_escrow").critical(
        "escrow_mismatch"
    )

    assert captured == [("escrow_mismatch", "fatal")]


def test_lower_severity_logs_are_not_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only CRITICAL is forwarded, so routine logs do not consume the quota."""
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        observability.sentry_sdk,
        "capture_message",
        lambda message, level="error": captured.append((message, level)),
    )
    monkeypatch.setattr(observability.sentry_sdk, "init", lambda **kwargs: None)
    observability.configure_error_tracking(
        _settings(SENTRY_DSN="https://public@example.ingest.sentry.io/1")
    )

    logger.bind(module="frameworks").info("published")
    logger.bind(module="frameworks").error("processing_failed")

    assert captured == []


def test_reconfiguring_survives_logging_being_reset_in_between(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reconfiguring after ``configure_logging`` runs must not raise.

    ``configure_logging`` calls ``logger.remove()``, which drops every sink
    including this module's. Its recorded sink id is then stale, and loguru
    raises on removing an id that no longer exists. ``create_app()`` performs
    exactly this sequence, so the naive implementation crashes on the second
    call rather than on the first.
    """
    monkeypatch.setattr(observability.sentry_sdk, "init", lambda **kwargs: None)
    settings = _settings(SENTRY_DSN="https://public@example.ingest.sentry.io/1")
    observability.configure_error_tracking(settings)

    configure_logging("text")

    observability.configure_error_tracking(settings)


def test_reconfiguring_does_not_stack_duplicate_sinks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configuring twice forwards each CRITICAL once, not twice.

    ``create_app()`` runs more than once across a test session and could run
    again under a reloader, and a duplicated sink would double every alert.
    """
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        observability.sentry_sdk,
        "capture_message",
        lambda message, level="error": captured.append((message, level)),
    )
    monkeypatch.setattr(observability.sentry_sdk, "init", lambda **kwargs: None)
    settings = _settings(SENTRY_DSN="https://public@example.ingest.sentry.io/1")

    observability.configure_error_tracking(settings)
    observability.configure_error_tracking(settings)

    logger.bind(module="financials").critical("double_charge_detected")

    assert captured == [("double_charge_detected", "fatal")]
