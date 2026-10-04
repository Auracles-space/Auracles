"""Tests for the PII blocking-finding selection policy.

Only genuinely sensitive entity types above the confidence threshold should
block publishing. Benign entities Presidio emits on ordinary framework prose
(notably DATE_TIME on "30 days", "Day 30") must not flag the artifact.
"""

from app.workers.tasks.processing.pii import (
    PII_CONFIDENCE_THRESHOLD,
    PiiFinding,
    pii_override_accepted,
    select_blocking_findings,
)


def _finding(entity_type: str, score: float) -> PiiFinding:
    """Build a PiiFinding with throwaway offsets for policy tests."""
    return PiiFinding(entity_type=entity_type, score=score, start=0, end=1)


def test_date_time_findings_never_block() -> None:
    """DATE_TIME is not sensitive PII and must not flag, even at high score."""
    findings = [_finding("DATE_TIME", 0.85) for _ in range(11)]

    assert select_blocking_findings(findings) == []


def test_sensitive_high_confidence_findings_block() -> None:
    """Contact and identity entities above the threshold flag for review."""
    email = _finding("EMAIL_ADDRESS", 0.97)
    person = _finding("PERSON", 0.85)

    blocking = select_blocking_findings([email, person])

    assert email in blocking
    assert person in blocking


def test_low_confidence_sensitive_findings_do_not_block() -> None:
    """A sensitive type below the confidence threshold is ignored."""
    weak = _finding("EMAIL_ADDRESS", PII_CONFIDENCE_THRESHOLD - 0.01)

    assert select_blocking_findings([weak]) == []


def test_mixed_findings_keep_only_sensitive_above_threshold() -> None:
    """Only the sensitive, high-confidence finding survives the filter."""
    date = _finding("DATE_TIME", 0.85)
    url = _finding("URL", 0.95)
    phone = _finding("PHONE_NUMBER", 0.9)

    blocking = select_blocking_findings([date, url, phone])

    assert blocking == [phone]


def test_citation_override_waives_the_hold_but_not_the_finding() -> None:
    """An accepted citation override stops a hold without hiding what was found.

    The scan still records the entity types, because an admin reviewing an
    override needs to see what the Contributor waved through. Only the block
    is lifted.
    """
    assert pii_override_accepted({"pii_override": {"accepted": True}}) is True


def test_an_unset_or_declined_override_still_holds() -> None:
    """Absent, empty, or explicitly declined overrides leave the gate closed."""
    assert pii_override_accepted({}) is False
    assert pii_override_accepted(None) is False
    assert pii_override_accepted({"pii_override": {}}) is False
    assert pii_override_accepted({"pii_override": {"accepted": False}}) is False
