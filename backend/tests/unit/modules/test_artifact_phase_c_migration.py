"""Phase C adds a content hash and a processing lease to artifacts."""

from __future__ import annotations


def test_artifact_model_exposes_content_hash_and_lease_columns() -> None:
    """The Artifact ORM model must carry the two Phase C columns."""
    from app.modules.frameworks.models_artifact import Artifact

    columns = Artifact.__table__.columns
    assert "content_sha256" in columns
    assert columns["content_sha256"].nullable is True
    assert "processing_started_at" in columns
    assert columns["processing_started_at"].nullable is True


def test_settings_expose_phase_c_ttls() -> None:
    """Config must expose the lease and orphan-sweep TTL knobs."""
    from app.core.config import get_settings

    settings = get_settings()
    assert settings.artifact_processing_lease_minutes == 30
    assert settings.artifact_orphan_sweep_minutes == 60
