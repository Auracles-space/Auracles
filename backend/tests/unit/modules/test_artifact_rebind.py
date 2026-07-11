"""Unit tests for connector artifact re-bind (attach / repoint / detach)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from tests.unit.modules.test_frameworks_source_preview import (  # noqa: F401
    source_preview_ctx,
)

pytestmark = pytest.mark.asyncio


async def test_bind_source_attaches_and_pulls_for_upload_artifact(
    monkeypatch, source_preview_ctx  # noqa: F811
):
    """Attaching a source to an upload artifact forks a bound google_drive row."""
    from app.integrations import google_drive
    from app.modules.frameworks import service
    from app.modules.frameworks.models_artifact import Artifact
    from app.modules.frameworks.schemas import BindSourceRequest
    from app.modules.integrations import service as integrations_service

    db, contributor, framework, artifact = source_preview_ctx
    artifact.source_kind = "upload"
    artifact.source_connection_id = None
    artifact.source_external_id = None
    artifact.processing_status = "processed"
    await db.commit()

    # Reuse the resync test's _patch_common shim inline:
    monkeypatch.setattr(
        service, "get_settings",
        lambda: SimpleNamespace(s3_artifacts_bucket="bucket",
                                artifact_processing_lease_minutes=30),
    )

    async def _loader(db, *, user_id, connection_id):
        from app.modules.integrations.models import OAuthConnection
        return (OAuthConnection(id=connection_id, user_id=user_id,
                                provider="google_drive", scopes="s", status="active"),
                "token")

    monkeypatch.setattr(integrations_service,
                        "get_active_connection_with_fresh_token", _loader)
    monkeypatch.setattr(service.s3.storage, "upload_bytes",
                        lambda bucket, key, body, mime_type: None)
    monkeypatch.setattr(
        service.s3.storage, "delete_prefix", lambda bucket, prefix: None
    )
    monkeypatch.setattr(service.s3.storage, "delete_object", lambda bucket, key: None)
    monkeypatch.setattr(
        service, "scan_artifact", SimpleNamespace(delay=lambda _id: None)
    )

    async def _meta(*, access_token, file_id):
        return {"id": file_id, "name": "doc.pdf", "mimeType": "application/pdf",
                "size": "11", "modifiedTime": "REV-A"}

    async def _download(*, access_token, file_id, export_mime, max_bytes):
        return b"ATTACHED-11"

    monkeypatch.setattr(google_drive, "get_drive_file_metadata", _meta)
    monkeypatch.setattr(google_drive, "download_drive_file", _download)

    from sqlalchemy import select

    from app.modules.integrations.models import OAuthConnection

    connection = await db.scalar(select(OAuthConnection))

    result = await service.bind_artifact_source(
        db, contributor, framework.id, artifact.id,
        BindSourceRequest(connection_id=connection.id, file_id="file-A"),
    )

    new_row = await db.get(Artifact, result.id)
    assert new_row.source_kind == "google_drive"
    assert new_row.source_external_id == "file-A"


async def test_detach_source_reverts_to_upload(
    monkeypatch, source_preview_ctx  # noqa: F811
):
    """Detach clears binding, keeps bytes, and purges the preview cache."""
    from app.modules.frameworks import service

    db, contributor, framework, artifact = source_preview_ctx
    artifact.processing_status = "processed"
    await db.commit()

    prefixes: list[str] = []
    monkeypatch.setattr(
        service, "get_settings",
        lambda: SimpleNamespace(s3_artifacts_bucket="bucket"),
    )
    monkeypatch.setattr(service.s3.storage, "delete_prefix",
                        lambda bucket, prefix: prefixes.append(prefix))

    result = await service.detach_artifact_source(
        db, contributor, framework.id, artifact.id
    )

    assert result.source_kind == "upload"
    from app.modules.frameworks.models_artifact import Artifact
    row = await db.get(Artifact, artifact.id)
    assert row.source_external_id is None
    assert row.source_connection_id is None
    assert (
        f"frameworks/{framework.id}/artifacts/{artifact.id}/source-preview/"
        in prefixes
    )


async def test_detach_upload_artifact_conflicts(
    monkeypatch, source_preview_ctx  # noqa: F811
):
    """Detaching an artifact that has no connector source raises 409 not_bound."""
    from app.modules.frameworks import service

    db, contributor, framework, artifact = source_preview_ctx
    artifact.source_kind = "upload"
    artifact.source_connection_id = None
    artifact.source_external_id = None
    artifact.processing_status = "processed"
    await db.commit()

    monkeypatch.setattr(
        service, "get_settings",
        lambda: SimpleNamespace(s3_artifacts_bucket="bucket"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.detach_artifact_source(db, contributor, framework.id, artifact.id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "not_bound"
