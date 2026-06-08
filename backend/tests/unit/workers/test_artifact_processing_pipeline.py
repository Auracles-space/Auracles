"""Tests for Artifact extraction and PII processing pipeline tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import engine
from app.core.security import hash_password
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import (
    Framework,
    FrameworkVersion,
    FrameworkVersionArtifact,
    License,
    Review,
)
from app.modules.frameworks.models_artifact import (
    Artifact,
    ArtifactDownload,
    ArtifactPiiAudit,
    ArtifactRarityAudit,
)
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import artifacts as artifact_tasks


class FakePipelineStorage:
    """S3 test double for pipeline download and redacted upload behavior."""

    def __init__(self) -> None:
        """Create empty upload history."""
        self.download_body: bytes | None = None
        self.uploads: dict[str, bytes] = {}

    def download_file(self, bucket: str, key: str, destination: str) -> None:
        """Write deterministic local input for extraction."""
        if self.download_body is not None:
            Path(destination).write_bytes(self.download_body)
            return
        Path(destination).write_text("local artifact placeholder", encoding="utf-8")

    def upload_bytes(
        self,
        bucket: str,
        key: str,
        body: bytes,
        mime_type: str,
    ) -> None:
        """Record a redacted object upload instead of touching S3."""
        self.uploads[key] = body


class FakePhraseCache:
    """Redis-like test double for external-rarity phrase cache behavior."""

    def __init__(self, cached: dict[str, str] | None = None) -> None:
        """Create an in-memory cache with optional preloaded values."""
        self.cached = cached or {}
        self.writes: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        """Return a cached phrase result."""
        return self.cached.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        """Record cache writes without touching Redis."""
        self.writes[key] = value


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure marketplace tables exist for pipeline tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def processing_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, Any]]:
    """Reset marketplace rows and install pipeline test doubles."""
    from app.workers.tasks.processing import extract

    fake_storage = FakePipelineStorage()
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    asyncio.run(engine.dispose())

    def cleanup() -> None:
        """Delete marketplace rows before users to satisfy foreign keys."""
        with session_factory() as session:
            session.query(Framework).update({Framework.preview_artifact_id: None})
            session.execute(delete(AuditLog))
            session.execute(delete(Review))
            session.execute(delete(ArtifactDownload))
            session.execute(delete(License))
            session.execute(delete(ArtifactRarityAudit))
            session.execute(delete(ArtifactPiiAudit))
            session.execute(delete(FrameworkVersionArtifact))
            session.execute(delete(FrameworkVersion))
            session.execute(delete(Artifact))
            session.execute(delete(Framework))
            session.execute(delete(UserRole))
            session.execute(delete(User))
            session.commit()

    cleanup()
    monkeypatch.setattr(artifact_tasks.s3, "storage", fake_storage)
    monkeypatch.setattr(extract.s3, "storage", fake_storage)
    try:
        yield {"storage": fake_storage}
    finally:
        cleanup()
        asyncio.run(engine.dispose())
        sync_engine.dispose()


def create_processing_artifact(
    *,
    name: str = "pipeline.pdf",
    mime_type: str = "application/pdf",
) -> UUID:
    """Create a clean Artifact ready for Slice 4 processing."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        user = User(
            email=f"pipeline-artifact-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="pipeline-artifact",
            email_verified=True,
            kyc_status="verified",
        )
        session.add(user)
        session.flush()
        session.add(
            UserRole(
                user_id=user.id,
                role="contributor",
                approved_at=datetime.now(UTC),
            )
        )
        framework = Framework(
            contributor_id=user.id,
            title="Pipeline Framework",
            description="Pipeline Framework description",
            category="Operations",
            tags=["risk", "governance"],
            tags_text="risk governance",
            price="100.00",
            currency="USD",
            license_types=["single_user"],
        )
        session.add(framework)
        session.flush()
        artifact = Artifact(
            framework_id=framework.id,
            name=name,
            file_key=f"frameworks/{framework.id}/artifacts/{name}",
            file_size=256,
            mime_type=mime_type,
            scan_status="clean",
            processing_status="processing",
        )
        session.add(artifact)
        session.flush()
        artifact_id = artifact.id
        session.commit()
    sync_engine.dispose()
    return artifact_id


def mark_framework_published(artifact_id: UUID) -> None:
    """Mark the owning Framework published so rarity can compare against it."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        artifact = session.get(Artifact, artifact_id)
        assert artifact is not None
        framework = session.get(Framework, artifact.framework_id)
        assert framework is not None
        framework.status = "published"
        artifact.processing_status = "processed"
        session.commit()
    sync_engine.dispose()


def set_preview_artifact(artifact_id: UUID) -> UUID:
    """Set an Artifact as its Framework's designated preview artifact."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        artifact = session.get(Artifact, artifact_id)
        assert artifact is not None
        framework = session.get(Framework, artifact.framework_id)
        assert framework is not None
        framework.preview_artifact_id = artifact.id
        framework_id = framework.id
        session.commit()
    sync_engine.dispose()
    return framework_id


def build_docx_bytes(text: str) -> bytes:
    """Build a minimal DOCX-like Office XML zip for extraction tests."""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
                f"{text}"
                "</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
    return buffer.getvalue()


def build_zip_bytes(entries: dict[str, bytes]) -> bytes:
    """Build an in-memory ZIP file for extraction tests."""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def build_png_bytes(color: tuple[int, int, int] = (220, 24, 24)) -> bytes:
    """Build a small PNG image used by deterministic thumbnail tests."""
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (80, 80), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def read_artifact_state(
    artifact_id: UUID,
) -> tuple[
    Artifact | None,
    ArtifactPiiAudit | None,
    ArtifactRarityAudit | None,
    AuditLog | None,
]:
    """Load the current Artifact, processing audits, and PII audit rows."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        artifact = session.get(Artifact, artifact_id)
        pii_audit = session.scalar(
            select(ArtifactPiiAudit).where(ArtifactPiiAudit.artifact_id == artifact_id)
        )
        audit_log = session.scalar(
            select(AuditLog).where(AuditLog.action == "artifact_pii_flagged")
        )
        rarity_audit = session.scalar(
            select(ArtifactRarityAudit).where(
                ArtifactRarityAudit.artifact_id == artifact_id
            )
        )
    sync_engine.dispose()
    return artifact, pii_audit, rarity_audit, audit_log


def read_processing_audit_counts(artifact_id: UUID) -> tuple[int, int]:
    """Count PII and rarity audit rows for one Artifact."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        pii_count = session.scalar(
            select(func.count(ArtifactPiiAudit.id)).where(
                ArtifactPiiAudit.artifact_id == artifact_id
            )
        )
        rarity_count = session.scalar(
            select(func.count(ArtifactRarityAudit.id)).where(
                ArtifactRarityAudit.artifact_id == artifact_id
            )
        )
    sync_engine.dispose()
    return int(pii_count or 0), int(rarity_count or 0)


def read_artifact_framework(
    artifact_id: UUID,
) -> tuple[Artifact | None, Framework | None]:
    """Load an Artifact and its owning Framework."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        artifact = session.get(Artifact, artifact_id)
        framework = None
        if artifact is not None:
            framework = session.get(Framework, artifact.framework_id)
    sync_engine.dispose()
    return artifact, framework


def read_processing_failure(
    artifact_id: UUID,
) -> tuple[Artifact | None, AuditLog | None]:
    """Load an Artifact and its extraction failure audit row."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        artifact = session.get(Artifact, artifact_id)
        audit_log = session.scalar(
            select(AuditLog).where(
                AuditLog.action == "artifact_processing_failed",
                AuditLog.target_id == artifact_id,
            )
        )
    sync_engine.dispose()
    return artifact, audit_log


def set_external_rarity_context(
    artifact_id: UUID,
    *,
    internal_rarity: Decimal,
    text: str,
    top_terms: list[str],
) -> None:
    """Seed Artifact metadata needed by the external rarity step."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        artifact = session.get(Artifact, artifact_id)
        assert artifact is not None
        artifact.internal_rarity = internal_rarity
        artifact.metadata_vector = {
            "extraction": {"text": text},
            "top_tfidf_terms": top_terms,
        }
        session.commit()
    sync_engine.dispose()


def set_blend_context(
    artifact_id: UUID,
    *,
    internal_rarity: Decimal,
    external_rarity: Decimal | None,
) -> None:
    """Seed Artifact scores needed by the final rarity blend step."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        artifact = session.get(Artifact, artifact_id)
        assert artifact is not None
        artifact.internal_rarity = internal_rarity
        artifact.external_rarity = external_rarity
        session.add(
            ArtifactRarityAudit(
                artifact_id=artifact_id,
                internal_jaccard=Decimal("1.0000") - internal_rarity,
                external_phrases_queried=["vendor risk workflow"],
                external_hit_counts=[1],
            )
        )
        session.commit()
    sync_engine.dispose()


def set_framework_tags_text(artifact_id: UUID, tags_text: str) -> UUID:
    """Overwrite tags_text to verify search-index refresh behavior."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        artifact = session.get(Artifact, artifact_id)
        assert artifact is not None
        framework = session.get(Framework, artifact.framework_id)
        assert framework is not None
        framework.tags_text = tags_text
        framework_id = framework.id
        session.commit()
    sync_engine.dispose()
    return framework_id


def framework_matches_search(framework_id: UUID, query: str) -> bool:
    """Return whether the Framework matches the expression-index search shape."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    with sync_engine.connect() as connection:
        matched = connection.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM frameworks
                    WHERE id = :framework_id
                    AND to_tsvector(
                        'english',
                        title || ' ' || description || ' ' || tags_text
                    ) @@ plainto_tsquery('english', :query)
                )
                """
            ),
            {"framework_id": framework_id, "query": query},
        )
    sync_engine.dispose()
    return bool(matched)


def test_process_artifact_flags_high_confidence_pii_for_review(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """High-confidence PII blocks processing until safe redaction is available."""
    from app.workers.tasks.processing import extract, pii

    artifact_id = create_processing_artifact()
    monkeypatch.setattr(
        extract,
        "extract_text_from_file",
        lambda *_: extract.ExtractionResult(
            text="Contact Ada Lovelace at ada@example.com.",
            headings=["Contacts"],
            table_count=1,
            word_count=6,
            image_count=0,
        ),
    )
    monkeypatch.setattr(
        pii,
        "detect_pii_from_text",
        lambda _: [
            pii.PiiFinding(entity_type="EMAIL_ADDRESS", score=0.97, start=23, end=38)
        ],
    )

    artifact_tasks.process_artifact.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, pii_audit, _, audit_log = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.metadata_vector is not None
    assert artifact.metadata_vector["extraction"]["word_count"] == 6
    assert artifact.pii_detected is True
    assert artifact.pii_review_needed is True
    assert artifact.clean_file_key is None
    assert processing_context["storage"].uploads == {}
    assert artifact.processing_status == "flagged_pii"
    assert pii_audit is not None
    assert pii_audit.pii_types_found == ["EMAIL_ADDRESS"]
    assert pii_audit.auto_redacted is False
    assert pii_audit.flagged_for_review is True
    assert audit_log is not None


def test_external_rarity_skips_internally_duplicate_artifact(
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """External search is skipped when internal rarity is already too low."""
    from app.workers.tasks.processing import rarity_external

    artifact_id = create_processing_artifact(name="internal-duplicate.pdf")
    set_external_rarity_context(
        artifact_id,
        internal_rarity=Decimal("0.5000"),
        text="Vendor risk workflow with due diligence controls.",
        top_terms=["vendor", "risk", "workflow", "controls"],
    )

    rarity_external.compute_external_rarity.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, _, rarity_audit, _ = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.external_rarity is None
    assert rarity_audit is not None
    assert rarity_audit.external_phrases_queried == []
    assert rarity_audit.external_hit_counts == []


def test_external_rarity_scores_public_web_hits(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """External rarity stores queried phrases and hit counts from web search."""
    from app.workers.tasks.processing import rarity_external

    artifact_id = create_processing_artifact(name="externally-rare.pdf")
    set_external_rarity_context(
        artifact_id,
        internal_rarity=Decimal("0.9000"),
        text=(
            "Vendor risk assessment workflow maps due diligence controls into "
            "board reporting cadence. Vendor risk evidence tracker links "
            "remediation owners to audit-ready governance checkpoints."
        ),
        top_terms=[
            "vendor",
            "risk",
            "assessment",
            "workflow",
            "controls",
            "governance",
            "evidence",
            "remediation",
        ],
    )
    queried: list[str] = []

    async def fake_search_phrase(phrase: str) -> int:
        """Return deterministic web hit counts without touching Brave."""
        queried.append(phrase)
        return 2 if "vendor risk" in phrase else 0

    monkeypatch.setattr(rarity_external, "search_external_phrase", fake_search_phrase)

    rarity_external.compute_external_rarity.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, _, rarity_audit, _ = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.external_rarity is not None
    assert Decimal("0.0000") <= artifact.external_rarity <= Decimal("1.0000")
    assert rarity_audit is not None
    assert rarity_audit.external_phrases_queried == queried
    assert rarity_audit.external_hit_counts == [
        2 if "vendor risk" in phrase else 0 for phrase in queried
    ]


@pytest.mark.asyncio
async def test_external_rarity_phrase_cache_avoids_brave_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cached phrase hit count avoids a paid Brave Search request."""
    from app.workers.tasks.processing import rarity_external

    phrase = "vendor risk assessment workflow"
    cache_key = rarity_external._cache_key(phrase)
    fake_cache = FakePhraseCache({cache_key: '{"total_hits": 7}'})
    called = False

    async def fail_if_called(_: str) -> object:
        """Fail the test if the live provider is called on cache hit."""
        nonlocal called
        called = True
        raise AssertionError("Brave Search should not be called.")

    monkeypatch.setattr(rarity_external, "get_redis", lambda: fake_cache)
    monkeypatch.setattr(rarity_external, "search_web", fail_if_called)

    hit_count = await rarity_external.search_external_phrase(phrase)

    assert hit_count == 7
    assert called is False
    assert fake_cache.writes == {}


def test_external_rarity_gracefully_degrades_when_brave_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Provider failures mark external check unavailable without hard-failing."""
    from app.integrations.brave_search import BraveSearchError
    from app.workers.tasks.processing import rarity_external

    artifact_id = create_processing_artifact(name="brave-unavailable.pdf")
    set_external_rarity_context(
        artifact_id,
        internal_rarity=Decimal("0.9500"),
        text=(
            "Audit governance evidence workflow maps risk controls into "
            "remediation reporting and board oversight cadence."
        ),
        top_terms=[
            "audit",
            "governance",
            "evidence",
            "workflow",
            "risk",
            "controls",
            "remediation",
            "reporting",
        ],
    )

    async def fail_search(_: str) -> int:
        """Simulate an exhausted Brave retry sequence."""
        raise BraveSearchError("Brave Search returned 429.")

    monkeypatch.setattr(rarity_external, "search_external_phrase", fail_search)

    rarity_external.compute_external_rarity.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, framework = read_artifact_framework(artifact_id)

    assert artifact is not None
    assert artifact.external_rarity is None
    assert framework is not None
    assert framework.pipeline_failure_reasons["external_check"] == "unavailable"


def test_final_rarity_blend_persists_score_and_audit(
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Final rarity blends internal, external, and metadata uplift scores."""
    from app.workers.tasks.processing import blend

    artifact_id = create_processing_artifact(name="blend.pdf")
    set_blend_context(
        artifact_id,
        internal_rarity=Decimal("0.8000"),
        external_rarity=Decimal("0.6000"),
    )

    blend.compute_final_rarity.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, _, rarity_audit, _ = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.rarity_score == Decimal("0.6400")
    assert artifact.processing_status == "processed"
    assert rarity_audit is not None
    assert rarity_audit.metadata_uplift == Decimal("0.0000")
    assert rarity_audit.blended_score == Decimal("0.6400")


def test_final_rarity_blend_reweights_when_external_rarity_missing(
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """A missing external check uses neutral external rarity in the blend."""
    from app.workers.tasks.processing import blend

    artifact_id = create_processing_artifact(name="blend-null-external.pdf")
    set_blend_context(
        artifact_id,
        internal_rarity=Decimal("0.8000"),
        external_rarity=None,
    )

    blend.compute_final_rarity.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, _, rarity_audit, _ = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.rarity_score == Decimal("0.6250")
    assert rarity_audit is not None
    assert rarity_audit.blended_score == Decimal("0.6250")


def test_thumbnail_generation_uses_preview_artifact_and_stores_framework_key(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Thumbnail task uploads a PNG for the preview artifact and stores its key."""
    from app.workers.tasks.processing import thumbnail

    artifact_id = create_processing_artifact(name="preview.pdf")
    framework_id = set_preview_artifact(artifact_id)
    monkeypatch.setattr(
        thumbnail,
        "render_pdf_thumbnail",
        lambda *_: b"PNG-BYTES",
    )

    thumbnail.make_thumbnail.apply(args=[str(framework_id)]).get()
    asyncio.run(engine.dispose())

    _, framework = read_artifact_framework(artifact_id)
    uploads = processing_context["storage"].uploads

    assert framework is not None
    assert framework.thumbnail_key == f"frameworks/{framework_id}/thumbnail.png"
    assert uploads[framework.thumbnail_key] == b"PNG-BYTES"


def test_thumbnail_generation_renders_standalone_image_artifact(
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Image artifacts are resized onto the standard thumbnail canvas."""
    from PIL import Image

    from app.workers.tasks.processing import thumbnail

    artifact_id = create_processing_artifact(
        name="cover.png",
        mime_type="image/png",
    )
    framework_id = set_preview_artifact(artifact_id)
    processing_context["storage"].download_body = build_png_bytes()

    thumbnail.make_thumbnail.apply(args=[str(framework_id)]).get()
    asyncio.run(engine.dispose())

    _, framework = read_artifact_framework(artifact_id)
    uploads = processing_context["storage"].uploads

    assert framework is not None
    rendered = Image.open(BytesIO(uploads[framework.thumbnail_key]))
    assert rendered.size == (400, 600)
    assert rendered.getpixel((200, 300)) == (220, 24, 24)


def test_thumbnail_generation_converts_office_artifact_to_preview_png(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Office artifacts use deterministic conversion instead of a generic icon."""
    from app.workers.tasks.processing import thumbnail

    artifact_id = create_processing_artifact(
        name="playbook.docx",
        mime_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )
    framework_id = set_preview_artifact(artifact_id)
    monkeypatch.setattr(
        thumbnail,
        "render_office_thumbnail",
        lambda *_: b"OFFICE-THUMBNAIL",
    )

    thumbnail.make_thumbnail.apply(args=[str(framework_id)]).get()
    asyncio.run(engine.dispose())

    _, framework = read_artifact_framework(artifact_id)
    uploads = processing_context["storage"].uploads

    assert framework is not None
    assert framework.thumbnail_key == f"frameworks/{framework_id}/thumbnail.png"
    assert uploads[framework.thumbnail_key] == b"OFFICE-THUMBNAIL"


def test_thumbnail_generation_uses_first_previewable_zip_member(
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """ZIP artifacts render the first safe previewable inner file."""
    from PIL import Image

    from app.workers.tasks.processing import thumbnail

    artifact_id = create_processing_artifact(
        name="framework-bundle.zip",
        mime_type="application/zip",
    )
    framework_id = set_preview_artifact(artifact_id)
    processing_context["storage"].download_body = build_zip_bytes(
        {
            "notes.txt": b"not previewable",
            "assets/cover.png": build_png_bytes(color=(18, 140, 82)),
        }
    )

    thumbnail.make_thumbnail.apply(args=[str(framework_id)]).get()
    asyncio.run(engine.dispose())

    _, framework = read_artifact_framework(artifact_id)
    uploads = processing_context["storage"].uploads

    assert framework is not None
    rendered = Image.open(BytesIO(uploads[framework.thumbnail_key]))
    assert rendered.size == (400, 600)
    assert rendered.getpixel((200, 300)) == (18, 140, 82)


def test_image_artifact_extraction_marks_ocr_needed(
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Image-only Artifacts are captured as low-confidence OCR candidates."""
    from app.workers.tasks.processing import extract

    artifact_id = create_processing_artifact(
        name="diagram.png",
        mime_type="image/png",
    )
    processing_context["storage"].download_body = build_png_bytes()

    extract.extract_text.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, _, _, _ = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.metadata_vector is not None
    assert artifact.metadata_vector["extraction"]["image_count"] == 1
    assert artifact.metadata_vector["extraction"]["quality"] == {
        "empty_text": True,
        "tiny_text": False,
        "image_heavy": True,
        "needs_ocr": True,
        "low_confidence": True,
        "reason_codes": ["empty_extraction", "image_heavy_extraction", "needs_ocr"],
    }


def test_search_index_refresh_syncs_tags_text_for_fts(
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Search refresh makes tag text searchable through the FTS expression."""
    from app.workers.tasks.processing import search_index

    artifact_id = create_processing_artifact(name="search.pdf")
    framework_id = set_framework_tags_text(artifact_id, tags_text="")

    assert framework_matches_search(framework_id, "governance") is False

    search_index.refresh_framework_tsvector.apply(args=[str(framework_id)]).get()
    asyncio.run(engine.dispose())

    assert framework_matches_search(framework_id, "governance") is True


def test_extract_text_can_rerun_without_duplicate_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Re-running extraction overwrites extraction metadata idempotently."""
    from app.workers.tasks.processing import extract

    artifact_id = create_processing_artifact()
    results = iter(
        [
            extract.ExtractionResult(
                text="First extraction.",
                headings=["First"],
                table_count=0,
                word_count=2,
                image_count=0,
            ),
            extract.ExtractionResult(
                text="Second extraction has more words.",
                headings=["Second"],
                table_count=2,
                word_count=5,
                image_count=1,
            ),
        ]
    )
    monkeypatch.setattr(extract, "extract_text_from_file", lambda *_: next(results))

    extract.extract_text.apply(args=[str(artifact_id)]).get()
    extract.extract_text.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, pii_audit, _, _ = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.metadata_vector is not None
    assert artifact.metadata_vector["extraction"]["text"] == (
        "Second extraction has more words."
    )
    assert artifact.metadata_vector["extraction"]["table_count"] == 2
    assert pii_audit is None


def test_extract_text_reads_supported_files_inside_zip(
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """ZIP Artifacts are containers whose supported inner files are extracted."""
    from app.workers.tasks.processing import extract

    storage = processing_context["storage"]
    storage.download_body = build_zip_bytes(
        {
            "framework/playbook.docx": build_docx_bytes(
                "Zip Operating Procedure Contact List"
            ),
            "framework/notes.txt": b"unsupported plain text",
        }
    )
    artifact_id = create_processing_artifact(
        name="framework-bundle.zip",
        mime_type="application/zip",
    )

    extract.extract_text.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, pii_audit, _, _ = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.metadata_vector is not None
    extraction = artifact.metadata_vector["extraction"]
    assert "Zip Operating Procedure Contact List" in extraction["text"]
    assert extraction["archive_file_count"] == 2
    assert extraction["archive_supported_file_count"] == 1
    assert extraction["archive_unsupported_file_count"] == 1
    assert pii_audit is None


def test_extract_text_rejects_zip_with_unsafe_path(
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """ZIP Artifacts with path traversal entries fail extraction safely."""
    from app.workers.tasks.processing import extract

    storage = processing_context["storage"]
    storage.download_body = build_zip_bytes(
        {"../evil.docx": build_docx_bytes("Should not be extracted")}
    )
    artifact_id = create_processing_artifact(
        name="unsafe.zip",
        mime_type="application/zip",
    )

    extract.extract_text.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, audit_log = read_processing_failure(artifact_id)

    assert artifact is not None
    assert artifact.processing_status == "failed"
    assert audit_log is not None
    assert audit_log.metadata_["step"] == "extract"


def test_process_artifact_computes_metadata_fingerprint_and_internal_rarity(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """A first Artifact gets metadata, fingerprint, and rarity of 1.0."""
    from app.workers.tasks.processing import extract, pii

    artifact_id = create_processing_artifact()
    monkeypatch.setattr(
        extract,
        "extract_text_from_file",
        lambda *_: extract.ExtractionResult(
            text=(
                "Risk control operating model with board governance, risk "
                "register cadence, audit ownership, and control evidence."
            ),
            headings=["Risk Control Operating Model"],
            table_count=1,
            word_count=16,
            image_count=0,
        ),
    )
    monkeypatch.setattr(pii, "detect_pii_from_text", lambda _: [])

    artifact_tasks.process_artifact.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, pii_audit, rarity_audit, _ = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.metadata_vector is not None
    assert artifact.metadata_vector["language"] == "en"
    assert "risk" in artifact.metadata_vector["top_tfidf_terms"]
    assert artifact.metadata_vector["tag_overlap_count"] == 2
    assert artifact.metadata_vector["tag_overlap_tags"] == ["risk", "governance"]
    assert artifact.metadata_vector["char_count"] > 0
    assert artifact.minhash_signature is not None
    assert len(artifact.minhash_signature) == 1024
    assert artifact.simhash is not None
    assert artifact.internal_rarity == Decimal("1.0000")
    assert artifact.nearest_match_id is None
    assert rarity_audit is not None
    assert rarity_audit.internal_jaccard == Decimal("0.0000")
    assert pii_audit is not None


def test_process_artifact_scores_duplicate_against_published_artifact(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """A duplicate upload has low internal rarity against published content."""
    from app.workers.tasks.processing import extract, pii

    duplicate_text = (
        "Vendor risk assessment workflow with due diligence checks, control "
        "mapping, audit evidence, remediation tracking, and board reporting."
    )
    monkeypatch.setattr(
        extract,
        "extract_text_from_file",
        lambda *_: extract.ExtractionResult(
            text=duplicate_text,
            headings=["Vendor Risk"],
            table_count=0,
            word_count=17,
            image_count=0,
        ),
    )
    monkeypatch.setattr(pii, "detect_pii_from_text", lambda _: [])

    published_artifact_id = create_processing_artifact(name="published.pdf")
    artifact_tasks.process_artifact.apply(args=[str(published_artifact_id)]).get()
    mark_framework_published(published_artifact_id)

    duplicate_artifact_id = create_processing_artifact(name="duplicate.pdf")
    artifact_tasks.process_artifact.apply(args=[str(duplicate_artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, _, rarity_audit, _ = read_artifact_state(duplicate_artifact_id)

    assert artifact is not None
    assert artifact.internal_rarity == Decimal("0.0000")
    assert artifact.nearest_match_id == published_artifact_id
    assert rarity_audit is not None
    assert rarity_audit.internal_jaccard == Decimal("1.0000")
    assert rarity_audit.nearest_match_id == published_artifact_id


def test_process_artifact_treats_empty_text_as_fully_rare(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """An empty extraction has no matchable shingles and rarity remains 1.0."""
    from app.workers.tasks.processing import extract, pii

    artifact_id = create_processing_artifact(name="empty.pdf")
    monkeypatch.setattr(
        extract,
        "extract_text_from_file",
        lambda *_: extract.ExtractionResult(
            text="",
            headings=[],
            table_count=0,
            word_count=0,
            image_count=0,
        ),
    )
    monkeypatch.setattr(pii, "detect_pii_from_text", lambda _: [])

    artifact_tasks.process_artifact.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, _, rarity_audit, _ = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.metadata_vector is not None
    assert artifact.metadata_vector["language"] == "unknown"
    assert artifact.metadata_vector["top_tfidf_terms"] == []
    assert artifact.metadata_vector["char_count"] == 0
    assert artifact.metadata_vector["extraction"]["quality"] == {
        "empty_text": True,
        "tiny_text": False,
        "image_heavy": False,
        "needs_ocr": False,
        "low_confidence": True,
        "reason_codes": ["empty_extraction"],
    }
    assert artifact.metadata_vector["minhash"]["shingle_count"] == 0
    assert artifact.metadata_vector["minhash"]["low_confidence"] is True
    assert artifact.internal_rarity == Decimal("1.0000")
    assert rarity_audit is not None
    assert rarity_audit.internal_jaccard == Decimal("0.0000")


def test_process_artifact_does_not_match_empty_text_against_empty_published(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Empty artifacts have no comparable shingles, even against each other."""
    from app.workers.tasks.processing import extract, pii

    monkeypatch.setattr(
        extract,
        "extract_text_from_file",
        lambda *_: extract.ExtractionResult(
            text="",
            headings=[],
            table_count=0,
            word_count=0,
            image_count=0,
        ),
    )
    monkeypatch.setattr(pii, "detect_pii_from_text", lambda _: [])

    published_artifact_id = create_processing_artifact(name="published-empty.pdf")
    artifact_tasks.process_artifact.apply(args=[str(published_artifact_id)]).get()
    mark_framework_published(published_artifact_id)

    candidate_artifact_id = create_processing_artifact(name="candidate-empty.pdf")
    artifact_tasks.process_artifact.apply(args=[str(candidate_artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, _, rarity_audit, _ = read_artifact_state(candidate_artifact_id)

    assert artifact is not None
    assert artifact.internal_rarity == Decimal("1.0000")
    assert artifact.nearest_match_id is None
    assert rarity_audit is not None
    assert rarity_audit.internal_jaccard == Decimal("0.0000")


def test_process_artifact_marks_tiny_docs_as_low_confidence(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """A tiny document produces one shingle and a low-confidence fingerprint."""
    from app.workers.tasks.processing import extract, pii

    artifact_id = create_processing_artifact(name="tiny.pdf")
    monkeypatch.setattr(
        extract,
        "extract_text_from_file",
        lambda *_: extract.ExtractionResult(
            text="Risk",
            headings=[],
            table_count=0,
            word_count=1,
            image_count=0,
        ),
    )
    monkeypatch.setattr(pii, "detect_pii_from_text", lambda _: [])

    artifact_tasks.process_artifact.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, _, _, _ = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.metadata_vector is not None
    assert artifact.metadata_vector["language"] == "unknown"
    assert artifact.metadata_vector["extraction"]["quality"] == {
        "empty_text": False,
        "tiny_text": True,
        "image_heavy": False,
        "needs_ocr": False,
        "low_confidence": True,
        "reason_codes": ["tiny_extraction"],
    }
    assert artifact.metadata_vector["minhash"]["shingle_count"] == 1
    assert artifact.metadata_vector["minhash"]["low_confidence"] is True


def test_process_artifact_marks_image_heavy_empty_text_as_needing_ocr(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Image-heavy extraction with no text is explicitly marked for OCR."""
    from app.workers.tasks.processing import extract, pii

    artifact_id = create_processing_artifact(name="scanned.pdf")
    monkeypatch.setattr(
        extract,
        "extract_text_from_file",
        lambda *_: extract.ExtractionResult(
            text="",
            headings=[],
            table_count=0,
            word_count=0,
            image_count=4,
        ),
    )
    monkeypatch.setattr(pii, "detect_pii_from_text", lambda _: [])

    artifact_tasks.process_artifact.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, _, _, _ = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.metadata_vector is not None
    assert artifact.metadata_vector["extraction"]["quality"] == {
        "empty_text": True,
        "tiny_text": False,
        "image_heavy": True,
        "needs_ocr": True,
        "low_confidence": True,
        "reason_codes": ["empty_extraction", "image_heavy_extraction", "needs_ocr"],
    }


def test_process_artifact_rerun_keeps_processing_audits_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Rerunning processing refreshes audit rows instead of duplicating them."""
    from app.workers.tasks.processing import extract, pii

    artifact_id = create_processing_artifact(name="rerun.pdf")
    monkeypatch.setattr(
        extract,
        "extract_text_from_file",
        lambda *_: extract.ExtractionResult(
            text=(
                "Control library with policy ownership, implementation "
                "evidence, review cadence, and risk scoring."
            ),
            headings=["Control Library"],
            table_count=0,
            word_count=12,
            image_count=0,
        ),
    )
    monkeypatch.setattr(pii, "detect_pii_from_text", lambda _: [])

    artifact_tasks.process_artifact.apply(args=[str(artifact_id)]).get()
    artifact_tasks.process_artifact.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, pii_audit, rarity_audit, _ = read_artifact_state(artifact_id)
    pii_count, rarity_count = read_processing_audit_counts(artifact_id)

    assert artifact is not None
    assert artifact.internal_rarity == Decimal("1.0000")
    assert pii_audit is not None
    assert rarity_audit is not None
    assert pii_count == 1
    assert rarity_count == 1


def test_process_artifact_flags_low_confidence_pii_for_review(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Low-confidence PII pauses the pipeline for Contributor review."""
    from app.workers.tasks.processing import extract, pii

    artifact_id = create_processing_artifact()
    monkeypatch.setattr(
        extract,
        "extract_text_from_file",
        lambda *_: extract.ExtractionResult(
            text="Possible phone number: 555-0100.",
            headings=[],
            table_count=0,
            word_count=4,
            image_count=0,
        ),
    )
    monkeypatch.setattr(
        pii,
        "detect_pii_from_text",
        lambda _: [
            pii.PiiFinding(entity_type="PHONE_NUMBER", score=0.45, start=23, end=31)
        ],
    )

    artifact_tasks.process_artifact.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, pii_audit, _, audit_log = read_artifact_state(artifact_id)

    assert artifact is not None
    assert artifact.pii_detected is False
    assert artifact.pii_review_needed is True
    assert artifact.clean_file_key is None
    assert artifact.processing_status == "flagged_pii"
    assert pii_audit is not None
    assert pii_audit.pii_types_found == ["PHONE_NUMBER"]
    assert pii_audit.auto_redacted is False
    assert pii_audit.flagged_for_review is True
    assert audit_log is not None


def test_process_artifact_marks_failed_when_extraction_fails(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database: None,
    processing_context: dict[str, Any],
) -> None:
    """Corrupt or unsupported files fail at extraction with an audit record."""
    from app.workers.tasks.processing import extract

    artifact_id = create_processing_artifact()

    def fail_extraction(*_: object) -> extract.ExtractionResult:
        """Simulate a parser failure from a corrupt source file."""
        raise ValueError("corrupt pdf")

    monkeypatch.setattr(extract, "extract_text_from_file", fail_extraction)

    artifact_tasks.process_artifact.apply(args=[str(artifact_id)]).get()
    asyncio.run(engine.dispose())

    artifact, audit_log = read_processing_failure(artifact_id)

    assert artifact is not None
    assert artifact.processing_status == "failed"
    assert audit_log is not None
    assert audit_log.metadata_["step"] == "extract"
