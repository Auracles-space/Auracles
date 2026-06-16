"""Resend error-classification and dispatch tests.

Covers ``app/integrations/resend.py`` failure handling. Provider errors are
classified as transient (retryable: per-second rate limit, network blips) or
permanent (non-retryable: daily-quota exhaustion, validation), so the Celery
wrappers retry only what is worth retrying and never loop a quota-burning storm.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from app.integrations import resend as resend_adapter
from app.integrations.resend import (
    PermanentEmailError,
    TransientEmailError,
    classify_email_error,
)


class _FakeSettings:
    """Minimal settings stand-in for exercising the EMAIL_SEND_ENABLED gate."""

    def __init__(self, *, email_send_enabled: bool) -> None:
        self.email_send_enabled = email_send_enabled
        self.resend_api_key = SecretStr("re_test")
        self.resend_from_address = "noreply@auracles.space"
        self.cors_origin_list = ["http://localhost:3000"]


def test_classify_daily_quota_is_permanent() -> None:
    """The daily-quota error must classify as permanent (do not retry)."""
    exc = RuntimeError("You have reached your daily email sending quota.")
    assert isinstance(classify_email_error(exc), PermanentEmailError)


def test_classify_per_second_rate_limit_is_transient() -> None:
    """The per-second rate-limit error must classify as transient (retry)."""
    exc = RuntimeError(
        "Too many requests. You can only make 5 requests per second."
    )
    assert isinstance(classify_email_error(exc), TransientEmailError)


def test_classify_unknown_error_is_transient() -> None:
    """An unrecognised provider/network error defaults to transient (retry)."""
    result = classify_email_error(RuntimeError("connection reset"))
    assert isinstance(result, TransientEmailError)


def test_dispatch_raises_permanent_on_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_dispatch`` maps a daily-quota provider error to PermanentEmailError."""
    import resend

    def _raise(_payload: Any) -> None:
        raise RuntimeError("You have reached your daily email sending quota.")

    monkeypatch.setattr(resend.Emails, "send", staticmethod(_raise))

    with pytest.raises(PermanentEmailError):
        resend_adapter._dispatch(
            {"from": "a@b.test", "to": "c@d.test", "subject": "s", "html": "h"}
        )


def test_dispatch_raises_transient_on_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_dispatch`` maps a per-second rate limit to TransientEmailError."""
    import resend

    def _raise(_payload: Any) -> None:
        raise RuntimeError("Too many requests. 5 requests per second.")

    monkeypatch.setattr(resend.Emails, "send", staticmethod(_raise))

    with pytest.raises(TransientEmailError):
        resend_adapter._dispatch(
            {"from": "a@b.test", "to": "c@d.test", "subject": "s", "html": "h"}
        )


def test_dispatch_success_sends_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful send forwards the payload to the Resend SDK once."""
    import resend

    sent: list[Any] = []
    monkeypatch.setattr(resend.Emails, "send", staticmethod(sent.append))

    resend_adapter._dispatch({"from": "a@b.test", "to": "c@d.test"})

    assert sent == [{"from": "a@b.test", "to": "c@d.test"}]


def test_delivery_disabled_logs_and_skips_resend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EMAIL_SEND_ENABLED=false logs the email and never calls Resend.

    Local/dev path: the verification token is logged so the flow can be
    completed without hitting Resend (and burning the daily quota).
    """
    import resend

    def _fail(_payload: Any) -> None:
        raise AssertionError("Resend must not be called when delivery is disabled")

    monkeypatch.setattr(resend.Emails, "send", staticmethod(_fail))
    monkeypatch.setattr(
        resend_adapter, "get_settings", lambda: _FakeSettings(email_send_enabled=False)
    )

    # Must return without raising and without sending.
    resend_adapter.send_verification_email("user@auracles.space", "tok-xyz")


def test_delivery_disabled_logs_token_in_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The disabled-mode log embeds the token in the message text.

    The dev (text) log format renders only ``{message}`` and drops bound extras,
    so the token must be in the message itself to be retrievable without JSON.
    """
    from loguru import logger as loguru_logger

    monkeypatch.setattr(
        resend_adapter, "get_settings", lambda: _FakeSettings(email_send_enabled=False)
    )
    messages: list[str] = []
    sink_id = loguru_logger.add(messages.append, format="{message}")
    try:
        resend_adapter.send_verification_email("user@auracles.space", "tok-XYZ")
    finally:
        loguru_logger.remove(sink_id)

    assert any("tok-XYZ" in message for message in messages)


def test_delivery_enabled_dispatches_to_resend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EMAIL_SEND_ENABLED=true sends the email through Resend as normal."""
    import resend

    sent: list[Any] = []
    monkeypatch.setattr(resend.Emails, "send", staticmethod(sent.append))
    monkeypatch.setattr(
        resend_adapter, "get_settings", lambda: _FakeSettings(email_send_enabled=True)
    )

    resend_adapter.send_verification_email("user@auracles.space", "tok-xyz")

    assert len(sent) == 1


def test_verification_email_renders_magic_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sent email links to /verify-email?token=<token> so users click, not type."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(resend_adapter, "_dispatch", captured.update)
    monkeypatch.setattr(
        resend_adapter, "get_settings", lambda: _FakeSettings(email_send_enabled=True)
    )

    resend_adapter.send_verification_email("user@auracles.space", "ev_TOKEN123")

    assert "/verify-email?token=ev_TOKEN123" in str(captured.get("html", ""))


def test_verification_email_logs_magic_link_when_delivery_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled-mode logs the full verify URL so local dev can click/paste it."""
    from loguru import logger as loguru_logger

    monkeypatch.setattr(
        resend_adapter, "get_settings", lambda: _FakeSettings(email_send_enabled=False)
    )
    messages: list[str] = []
    sink_id = loguru_logger.add(messages.append, format="{message}")
    try:
        resend_adapter.send_verification_email("user@auracles.space", "ev_TOKEN123")
    finally:
        loguru_logger.remove(sink_id)

    assert any("/verify-email?token=ev_TOKEN123" in message for message in messages)


def test_password_reset_email_renders_magic_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sent email links to /reset-password?token=<token> so users click, not type."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(resend_adapter, "_dispatch", captured.update)
    monkeypatch.setattr(
        resend_adapter, "get_settings", lambda: _FakeSettings(email_send_enabled=True)
    )

    resend_adapter.send_password_reset_email("user@auracles.space", "rp_TOKEN123")

    assert "/reset-password?token=rp_TOKEN123" in str(captured.get("html", ""))


def test_password_reset_email_logs_magic_link_when_delivery_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled-mode logs the full reset URL so local dev can click/paste it."""
    from loguru import logger as loguru_logger

    monkeypatch.setattr(
        resend_adapter, "get_settings", lambda: _FakeSettings(email_send_enabled=False)
    )
    messages: list[str] = []
    sink_id = loguru_logger.add(messages.append, format="{message}")
    try:
        resend_adapter.send_password_reset_email("user@auracles.space", "rp_TOKEN123")
    finally:
        loguru_logger.remove(sink_id)

    assert any("/reset-password?token=rp_TOKEN123" in message for message in messages)
