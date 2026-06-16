"""Resend error-classification and dispatch tests.

Covers ``app/integrations/resend.py`` failure handling. Provider errors are
classified as transient (retryable: per-second rate limit, network blips) or
permanent (non-retryable: daily-quota exhaustion, validation), so the Celery
wrappers retry only what is worth retrying and never loop a quota-burning storm.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.integrations import resend as resend_adapter
from app.integrations.resend import (
    PermanentEmailError,
    TransientEmailError,
    classify_email_error,
)


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
