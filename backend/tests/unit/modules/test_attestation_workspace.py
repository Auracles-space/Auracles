"""Unit smoke tests for Module 4 workspace ORM surface."""

from __future__ import annotations

from app.modules.attestation import models


def test_in_review_status_registered() -> None:
    """The attestation status enum includes the new in_review working state."""
    assert "in_review" in models.ATTESTATION_STATUS_ENUM.enums


def test_new_workspace_tables_declared() -> None:
    """All Module 4 child tables are mapped."""
    for table in (
        "attestation_rubric_dimensions",
        "attestation_rubric_methodology",
        "attestation_rubric_scores",
        "attestation_annotations",
        "attestation_clarifications",
    ):
        assert table in models.Base.metadata.tables


def test_attestation_gains_workspace_columns() -> None:
    """Attestation and AttestorProfile carry the new workspace columns."""
    attestation_columns = models.Attestation.__table__.columns
    for name in (
        "review_started_at",
        "rubric_version",
        "conditions",
        "submitted_late",
    ):
        assert name in attestation_columns

    assert "late_submission_count" in models.AttestorProfile.__table__.columns
