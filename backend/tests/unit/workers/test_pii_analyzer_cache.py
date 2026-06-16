"""Tests for the Presidio analyzer process-cache in the PII step.

AnalyzerEngine loads the spaCy en_core_web_lg model (hundreds of MB). Building
it per task multiplied worker memory and caused Render OOM restarts. The
analyzer must be built once per worker process and reused.
"""

import pytest

from app.workers.tasks.processing import pii


def test_get_analyzer_builds_once_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """detect_pii_from_text reuses a single cached AnalyzerEngine, not one per call."""
    build_calls = {"count": 0}

    class FakeAnalyzer:
        def analyze(self, text: str, language: str) -> list:
            return []

    def fake_build() -> FakeAnalyzer:
        build_calls["count"] += 1
        return FakeAnalyzer()

    pii._get_analyzer.cache_clear()
    monkeypatch.setattr(pii, "_build_analyzer", fake_build)

    pii.detect_pii_from_text("first call")
    pii.detect_pii_from_text("second call")

    assert build_calls["count"] == 1

    pii._get_analyzer.cache_clear()
