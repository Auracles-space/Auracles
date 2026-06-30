"""Unit tests for the CoiEntry conflict-link extension.

Verifies the optional subject_id / subject_kind fields parse and that legacy
entries without them still validate (pre-launch, no backfill).

Maps to: spec §4 (CoI conflict-link schema).
"""

from __future__ import annotations

from uuid import uuid4

from app.modules.attestation.schemas import CoiEntry


def test_coi_entry_accepts_subject_link():
    """A declaration may link directly to a platform subject."""
    subject = uuid4()
    entry = CoiEntry(
        entity="Acme Capital",
        entity_type="firm",
        relationship="financial",
        within_24mo=True,
        subject_id=subject,
        subject_kind="user",
    )
    assert entry.subject_id == subject
    assert entry.subject_kind == "user"


def test_coi_entry_without_subject_is_valid():
    """Legacy declarations without linked subjects must still validate."""
    entry = CoiEntry(
        entity="External Person",
        entity_type="individual",
        relationship="advisory",
        within_24mo=False,
    )
    assert entry.subject_id is None
    assert entry.subject_kind is None
