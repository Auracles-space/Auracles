"""Unit tests for Credential verification schemas and service state machine."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.attestation.schemas import (
    AdminCredentialRejectRequest,
    CredentialCreateRequest,
)


def test_create_request_accepts_new_metadata_fields() -> None:
    """Create request accepts credential_type, verification_url, reference, issuer."""
    request = CredentialCreateRequest(
        title="PMP",
        issuer="PMI",
        issued_date="2024-01-01",
        credential_type="PMP",
        verification_url="https://verify.pmi.org/x",
        reference_number="PMP-12345",
        issuer_type="association",
    )
    assert request.credential_type == "PMP"
    assert request.issuer_type == "association"


def test_create_request_rejects_unknown_issuer_type() -> None:
    """issuer_type is constrained to the four-value taxonomy."""
    with pytest.raises(ValidationError):
        CredentialCreateRequest(
            title="PMP",
            issuer="PMI",
            issued_date="2024-01-01",
            issuer_type="bank",
        )


def test_reject_request_requires_non_empty_reason() -> None:
    """Admin reject must carry a reason."""
    with pytest.raises(ValidationError):
        AdminCredentialRejectRequest(reason="")
