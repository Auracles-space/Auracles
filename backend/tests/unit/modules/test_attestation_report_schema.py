"""Validation tests for the attestor report submission schema.

The report-length quality gate (>=150 words across rubric comments, summary,
and conditions) is the substantive bar for report body length. The per-field
character floors on summary and scope only guarantee the required fields are
non-empty; they must not impose a second, competing length rule.
"""

import pytest
from pydantic import ValidationError

from app.modules.attestation.schemas import AttestationReportSubmitRequest


def test_short_nonempty_summary_and_scope_are_valid():
    """Summary and scope only need to be non-empty; the word gate governs length.

    A short-but-present summary/scope passes schema validation so the 150-word
    report-length gate is the single length authority, rather than 422-ing on a
    field character minimum the reviewer never saw.
    """
    payload = AttestationReportSubmitRequest(
        outcome="approved",
        summary="Solid.",
        scope="Full docs.",
        conditions=None,
        evidence_references={},
    )
    assert payload.summary == "Solid."
    assert payload.scope == "Full docs."


@pytest.mark.parametrize("field", ["summary", "scope"])
def test_empty_required_field_is_rejected(field: str):
    """An empty summary or scope is still a required-field violation."""
    kwargs = {
        "outcome": "approved",
        "summary": "Solid.",
        "scope": "Full docs.",
        "conditions": None,
        "evidence_references": {},
    }
    kwargs[field] = ""
    with pytest.raises(ValidationError):
        AttestationReportSubmitRequest(**kwargs)
