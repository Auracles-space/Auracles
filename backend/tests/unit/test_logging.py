"""Unit tests for the local-development log formatter.

Loguru captures log kwargs into `record["extra"]`, so the fields a call site
binds are always present on the record. The production JSON sink serializes
them automatically; the development sink formats them itself, and these tests
pin the two behaviours that formatter has to guarantee:

1. Bound fields reach the rendered line, so a developer reading local output
   sees the same detail the JSON sink would have written.
2. Rendering never raises — not for a call that binds no context, and not for
   a field value that happens to contain format or markup syntax.

Each test drives the real `configure_logging` entry point and reads back
stdout, so the wiring is covered rather than the formatter in isolation.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from loguru import logger

from app.core.logging import configure_logging


@pytest.fixture(autouse=True)
def _reset_log_sinks() -> Iterator[None]:
    """Drop every sink after each test so none outlives its capture buffer."""
    yield
    logger.remove()


# `configure_logging` must be called inside the test body, never from a fixture:
# Loguru binds the stream object at `add()` time, and pytest installs a fresh
# capture buffer for the call phase while closing the one live during setup. A
# sink added during setup therefore writes into a closed file and the record is
# lost to a swallowed `ValueError` on stderr.


def test_bound_field_is_rendered_in_dev_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A field bound as a log kwarg must appear in the formatted dev line.

    Regression: the previous static format string named only `module` and
    `action`, so `logger.error("database_ping_failed", error=...)` rendered as
    a bare event name and the captured exception detail was invisible locally.
    """
    configure_logging("text")

    logger.bind(module="health", action="check_database").error(
        "database_ping_failed", error="the greenlet library is required"
    )

    line = capsys.readouterr().out
    assert "health.check_database" in line
    assert "database_ping_failed" in line
    assert "error=the greenlet library is required" in line


def test_log_without_bound_context_does_not_raise(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A call binding neither module nor action must still render.

    Regression: `{extra[module]}` is a hard subscript, so an unbound call
    raised KeyError inside the handler and printed a traceback instead of the
    log line — in development only, while production JSON logged it fine.
    Loguru swallows handler errors to stderr, so stderr is asserted too.
    """
    configure_logging("text")

    logger.info("some_unbound_event")

    captured = capsys.readouterr()
    assert "some_unbound_event" in captured.out
    assert "KeyError" not in captured.err
    assert "Logging error" not in captured.err


def test_field_values_containing_format_syntax_are_not_interpreted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Braces inside a field value must render literally, not re-format.

    Exception strings routinely contain `{...}`; substituting one into the
    format string would raise or, worse, resolve against the record.
    """
    configure_logging("text")

    logger.bind(module="workers", action="run_task").error(
        "task_failed", error="KeyError: {module} {0} {}"
    )

    captured = capsys.readouterr()
    assert "error=KeyError: {module} {0} {}" in captured.out
    assert "Logging error" not in captured.err


def test_context_helper_keys_do_not_leak_into_rendered_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Formatter-internal keys must not surface as user-visible fields.

    The formatter stashes computed values on `record["extra"]`; a record sent
    to a second sink is formatted twice, so those keys must stay suppressed.
    """
    configure_logging("text")

    logger.bind(module="health", action="check_redis").warning(
        "redis_slow", latency_ms=812
    )

    line = capsys.readouterr().out
    assert "latency_ms=812" in line
    assert "_context" not in line
    assert "_fields" not in line


def test_json_sink_still_serializes_bound_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Production JSON output must keep carrying bound fields unchanged.

    The dev formatter is the only thing changing; this pins the sink that was
    already correct so a future format edit cannot regress prod observability.
    """
    configure_logging("json")

    logger.bind(module="health", action="check_database").error(
        "database_ping_failed", error="connection refused"
    )

    payload = json.loads(capsys.readouterr().out.strip())["record"]
    assert payload["message"] == "database_ping_failed"
    assert payload["extra"]["error"] == "connection refused"
