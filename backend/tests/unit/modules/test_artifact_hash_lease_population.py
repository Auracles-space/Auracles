"""Import stamps content hash + processing lease on connector artifacts."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from tests.unit.modules.test_frameworks_source_preview import (
    _fake_connection,
    source_preview_ctx,  # noqa: F401
)

pytestmark = pytest.mark.asyncio


async def test_import_stamps_content_hash_and_lease(
    monkeypatch: pytest.MonkeyPatch,
    source_preview_ctx: tuple,  # noqa: F811
) -> None:
    """A connector import records sha256(body) and processing_started_at."""
    from app.integrations import google_drive
    from app.modules.frameworks import service
    from app.modules.frameworks.models_artifact import Artifact
    from app.modules.frameworks.schemas import ArtifactFromConnectorRequest
    from app.modules.integrations import service as integrations_service

    db, contributor, framework, artifact = source_preview_ctx
    body = b"PDF-BYTES-HERE"
    connection_id: UUID = artifact.source_connection_id

    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(s3_artifacts_bucket="bucket"),
    )
    monkeypatch.setattr(
        integrations_service,
        "get_active_connection_with_fresh_token",
        _fake_connection(connection_id),
    )

    async def _meta(*, access_token: str, file_id: str) -> dict:
        return {
            "id": file_id,
            "name": "brief.pdf",
            "mimeType": "application/pdf",
            "size": str(len(body)),
            "modifiedTime": "REV-1",
        }

    async def _download(
        *, access_token: str, file_id: str, export_mime: str | None, max_bytes: int
    ) -> bytes:
        return body

    monkeypatch.setattr(google_drive, "get_drive_file_metadata", _meta)
    monkeypatch.setattr(google_drive, "download_drive_file", _download)
    monkeypatch.setattr(
        service.s3.storage,
        "upload_bytes",
        lambda bucket, key, body, mime_type: None,
    )
    monkeypatch.setattr(
        service, "scan_artifact", SimpleNamespace(delay=lambda _id: None)
    )

    await service.import_artifact_from_connector(
        db,
        contributor,
        framework.id,
        ArtifactFromConnectorRequest(connection_id=connection_id, file_id="file-9"),
    )

    row = await db.scalar(
        select(Artifact).where(Artifact.source_external_id == "file-9")
    )
    assert row is not None
    assert row.content_sha256 == hashlib.sha256(body).hexdigest()
    assert row.processing_started_at is not None
