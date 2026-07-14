"""Unit tests for Organizations request-schema field validation.

Focuses on the shared prose guard used by attestor-application and legal-profile
text fields: it must block markup delimiters and dangerous control characters
while allowing the whitespace people naturally type in multi-line textareas.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.organizations.schemas import (
    OrgAttestorApplicationCreateRequest,
    OrgLegalProfileUpdateRequest,
)


def _valid_application(**overrides: object) -> dict[str, object]:
    """Build a minimally valid attestor-application payload for schema tests."""
    payload: dict[str, object] = {
        "sectors": ["private_equity"],
        "functions": ["compliance"],
        "jurisdictions": ["united_states"],
        "credentials_summary": "Ten years auditing PE funds across the US.",
        "professional_references": "Jane Doe, jane@example.com",
    }
    payload.update(overrides)
    return payload


def test_prose_field_allows_newlines_and_tabs() -> None:
    """Multi-line textarea prose (newlines, tabs) must pass validation.

    Regression: the prose guard rejected any control character, so pressing
    Enter in the Credentials Summary / Professional References textareas raised
    a 422. Newline, tab, and carriage return are legitimate prose whitespace.
    """
    request = OrgAttestorApplicationCreateRequest.model_validate(
        _valid_application(
            credentials_summary="First line.\nSecond line.\tIndented.",
            professional_references="Ref one.\r\nRef two.",
        )
    )
    assert "\n" in request.credentials_summary
    assert "\r\n" in request.professional_references


@pytest.mark.parametrize("bad", ["a<script>b", "greater > than", "null\x00byte"])
def test_prose_field_still_blocks_markup_and_null(bad: str) -> None:
    """Angle brackets and non-whitespace control characters remain rejected."""
    with pytest.raises(ValidationError):
        OrgAttestorApplicationCreateRequest.model_validate(
            _valid_application(credentials_summary=bad)
        )


def test_legal_profile_text_still_blocks_markup() -> None:
    """The legal-profile prose guard keeps rejecting markup delimiters."""
    with pytest.raises(ValidationError):
        OrgLegalProfileUpdateRequest.model_validate(
            {"legal_name": "Evil<b>Corp", "totp_code": "123456"}
        )
