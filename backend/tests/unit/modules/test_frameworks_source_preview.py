"""Unit tests for the draft source-preview service."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.modules.integrations.models import OAuthConnection


def _fake_connection(
    connection_id: UUID,
) -> Callable[..., Awaitable[tuple[OAuthConnection, str]]]:
    """Return a connection-loader stub that yields a fake access token."""

    async def _loader(
        db: AsyncSession, *, user_id: UUID, connection_id: UUID
    ) -> tuple[OAuthConnection, str]:
        """Return a minimal connection row and a fake access token."""
        return (
            OAuthConnection(
                id=connection_id,
                user_id=user_id,
                provider="google_drive",
                scopes="https://www.googleapis.com/auth/drive.readonly",
                status="active",
            ),
            "access-token",
        )

    return _loader


async def _cleanup_preview_rows() -> None:
    """Remove preview-test rows in FK-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(Artifact))
        await session.execute(delete(Framework))
        await session.execute(delete(OAuthConnection))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture
async def source_preview_ctx(
    migrated_database: None,
) -> AsyncIterator[tuple[AsyncSession, User, Framework, Artifact]]:
    """Seed a draft framework with one google_drive artifact and open a session."""
    await engine.dispose()
    await _cleanup_preview_rows()

    session = async_session_factory()
    contributor = User(
        email="preview-owner@auracles.space",
        display_name="Preview Owner",
        email_verified=True,
        password_hash=None,
    )
    framework = Framework(
        contributor_id=uuid4(),
        title="Previewable Framework",
        description="Draft framework for source preview tests.",
        category="framework",
        sector="financial_services",
        industry="fund_management",
        business_function="risk_management",
        tags=["preview"],
        tags_text="preview",
        jurisdiction="us",
        complexity=3,
        org_size="mid_market",
        lifecycle_stage="scale",
        price=Decimal("499.00"),
        currency="USD",
        license_types=["single_user"],
        commercial_rights="Internal commercial use allowed.",
        usage_restrictions="No resale.",
        status="draft",
    )
    connection = OAuthConnection(
        user_id=uuid4(),
        provider="google_drive",
        scopes="https://www.googleapis.com/auth/drive.readonly",
        status="active",
    )
    artifact = Artifact(
        framework_id=uuid4(),
        name="brief.pdf",
        file_key="frameworks/fw/artifacts/art.pdf",
        file_size=13,
        mime_type="application/pdf",
        processing_status="processing",
        source_kind="google_drive",
        source_external_id="file-1",
        source_connection_id=uuid4(),
        source_last_synced_at=datetime(2026, 7, 8, tzinfo=UTC),
        source_synced_revision="REV-OLD",
    )

    async with session.begin():
        session.add(contributor)
        await session.flush()
        framework.contributor_id = contributor.id
        session.add(framework)
        await session.flush()
        connection.user_id = contributor.id
        session.add(connection)
        await session.flush()
        artifact.framework_id = framework.id
        artifact.source_connection_id = connection.id
        session.add(artifact)
        await session.flush()

    yield session, contributor, framework, artifact

    await session.close()
    await _cleanup_preview_rows()
    await engine.dispose()


@pytest.mark.asyncio
async def test_source_preview_reports_updated_when_revision_changed(
    monkeypatch: pytest.MonkeyPatch,
    source_preview_ctx: tuple[AsyncSession, User, Framework, Artifact],
) -> None:
    """A changed Drive modifiedTime returns source_updated and a presigned URL."""
    from app.integrations import google_drive
    from app.modules.frameworks import service
    from app.modules.integrations import service as integrations_service

    db, contributor, framework, artifact = source_preview_ctx
    exists_calls: list[str] = []

    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(s3_artifacts_bucket="artifacts-bucket"),
    )
    monkeypatch.setattr(
        integrations_service,
        "get_active_connection_with_fresh_token",
        _fake_connection(artifact.source_connection_id),
    )

    async def _state(*, access_token: str, file_id: str) -> tuple[str, str | None]:
        """Return a newer revision and a valid Google thumbnail host."""
        return "REV-NEW", "https://lh3.googleusercontent.com/t.png"

    async def _thumb(
        *, thumbnail_link: str, access_token: str, max_bytes: int
    ) -> bytes:
        """Return a small thumbnail payload."""
        return b"PNGDATA"

    monkeypatch.setattr(google_drive, "fetch_drive_source_state", _state, raising=False)
    monkeypatch.setattr(google_drive, "download_drive_thumbnail", _thumb)

    def _object_exists(bucket: str, key: str) -> bool:
        """Miss before upload, hit after upload."""
        exists_calls.append(key)
        return len(exists_calls) > 1

    monkeypatch.setattr(service.s3.storage, "object_exists", _object_exists)
    monkeypatch.setattr(
        service.s3.storage,
        "upload_bytes",
        lambda bucket, key, body, mime_type: None,
    )
    monkeypatch.setattr(
        service.s3.storage,
        "delete_prefix",
        lambda bucket, prefix: None,
    )
    monkeypatch.setattr(
        service.s3.storage,
        "presigned_get",
        lambda bucket, key, expires_in: "https://s3/presigned",
    )

    result = await service.get_source_preview(
        db,
        contributor,
        framework.id,
        artifact.id,
    )

    assert result.source_updated is True
    assert result.preview_url == "https://s3/presigned"
    assert len(exists_calls) == 2


@pytest.mark.asyncio
async def test_source_preview_refuses_upload_artifact(
    source_preview_ctx: tuple[AsyncSession, User, Framework, Artifact],
) -> None:
    """Upload-kind artifacts have no bound source and must 404."""
    from app.modules.frameworks import service

    db, contributor, framework, artifact = source_preview_ctx
    artifact.source_kind = "upload"
    artifact.source_connection_id = None
    artifact.source_external_id = None
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await service.get_source_preview(db, contributor, framework.id, artifact.id)

    assert exc_info.value.status_code == 404


def test_artifact_response_has_no_source_preview_fields() -> None:
    """ArtifactResponse must stay free of preview-only and secret source fields."""
    from app.modules.frameworks.schemas import ArtifactResponse

    forbidden = {
        "preview_url",
        "source_updated",
        "source_external_id",
        "source_connection_id",
        "source_synced_revision",
    }
    assert forbidden.isdisjoint(ArtifactResponse.model_fields.keys())
