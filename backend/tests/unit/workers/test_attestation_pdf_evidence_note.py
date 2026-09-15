"""The report PDF describes attached evidence without exposing storage paths.

The PDF used to print ``str(evidence_references)``, which put internal S3 keys
into a document the requestor downloads.
"""

from __future__ import annotations

from app.workers.tasks.attestation_pdf import evidence_note


def test_evidence_note_counts_files_without_storage_paths() -> None:
    """Attached files are counted; their S3 keys never reach the PDF."""
    note = evidence_note(
        {
            "file_keys": [
                "attestations/a/evidence/u/1-cac.pdf",
                "attestations/a/evidence/u/2-bank.pdf",
            ]
        }
    )

    assert note == "2 evidence files attached."
    assert "attestations/" not in note


def test_evidence_note_uses_the_singular_for_one_file() -> None:
    """One file reads naturally."""
    assert evidence_note({"file_keys": ["k"]}) == "1 evidence file attached."


def test_evidence_note_is_empty_without_files() -> None:
    """No evidence means no supplementary note at all."""
    assert evidence_note({}) is None
    assert evidence_note(None) is None
    assert evidence_note({"file_keys": []}) is None
