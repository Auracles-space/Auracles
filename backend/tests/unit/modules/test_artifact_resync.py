"""Unit tests for connector artifact re-sync (fork-per-change)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from tests.unit.modules.test_frameworks_source_preview import (  # noqa: F401
    source_preview_ctx,
)

pytestmark = pytest.mark.asyncio


def _patch_common(monkeypatch, service, integrations_service, artifact):
    """Stub settings, connection, S3 side effects, and the scan dispatch."""
    monkeypatch.setattr(
        service, "get_settings",
        lambda: SimpleNamespace(
            s3_artifacts_bucket="bucket", artifact_processing_lease_minutes=30
        ),
    )

    async def _loader(db, *, user_id, connection_id):
        from app.modules.integrations.models import OAuthConnection
        return (
            OAuthConnection(id=connection_id, user_id=user_id,
                            provider="google_drive", scopes="s", status="active"),
            "token",
        )

    monkeypatch.setattr(
        integrations_service, "get_active_connection_with_fresh_token", _loader
    )
    monkeypatch.setattr(service.s3.storage, "upload_bytes",
                        lambda bucket, key, body, mime_type: None)
    monkeypatch.setattr(
        service.s3.storage, "delete_prefix", lambda bucket, prefix: None
    )
    monkeypatch.setattr(service.s3.storage, "delete_object", lambda bucket, key: None)
    monkeypatch.setattr(service, "scan_artifact",
                        SimpleNamespace(delay=lambda _id: None))


async def test_resync_forks_new_row_on_drift(
    monkeypatch: pytest.MonkeyPatch,
    source_preview_ctx: tuple,  # noqa: F811
):
    """A changed source forks a new current artifact and retires the old id."""
    from app.integrations import google_drive
    from app.modules.frameworks import service
    from app.modules.frameworks.models_artifact import Artifact
    from app.modules.integrations import service as integrations_service

    db, contributor, framework, artifact = source_preview_ctx
    artifact.processing_status = "processed"
    artifact.content_sha256 = "OLD-HASH"
    await db.commit()
    old_id = artifact.id
    new_body = b"NEW-CONTENT"

    _patch_common(monkeypatch, service, integrations_service, artifact)

    async def _meta(*, access_token, file_id):
        return {"id": file_id, "name": "brief.pdf", "mimeType": "application/pdf",
                "size": str(len(new_body)), "modifiedTime": "REV-NEW"}

    async def _download(*, access_token, file_id, export_mime, max_bytes):
        return new_body

    monkeypatch.setattr(google_drive, "get_drive_file_metadata", _meta)
    monkeypatch.setattr(google_drive, "download_drive_file", _download)

    result = await service.resync_artifact(db, contributor, framework.id, old_id)

    assert result.id != old_id
    new_row = await db.get(Artifact, result.id)
    assert new_row.current_for_framework is True
    assert new_row.source_synced_revision == "REV-NEW"
    assert new_row.content_sha256 == hashlib.sha256(new_body).hexdigest()
    assert new_row.processing_status == "processing"
    old_row = await db.get(Artifact, old_id)
    # Unreferenced old row is deleted.
    assert old_row is None


def _stub_drive(monkeypatch, google_drive, *, name="brief.pdf", size, modified_time):
    """Stub Drive metadata + download to return the given body/revision."""

    async def _meta(*, access_token, file_id):
        return {"id": file_id, "name": name, "mimeType": "application/pdf",
                "size": str(size), "modifiedTime": modified_time}

    monkeypatch.setattr(google_drive, "get_drive_file_metadata", _meta)


async def test_resync_content_skip_when_bytes_identical(
    monkeypatch: pytest.MonkeyPatch,
    source_preview_ctx: tuple,  # noqa: F811
):
    """Identical bytes under a bumped revision advance markers without forking."""
    from app.integrations import google_drive
    from app.modules.frameworks import service
    from app.modules.frameworks.models_artifact import Artifact
    from app.modules.integrations import service as integrations_service

    db, contributor, framework, artifact = source_preview_ctx
    same_body = b"SAME-CONTENT"
    artifact.processing_status = "processed"
    artifact.content_sha256 = hashlib.sha256(same_body).hexdigest()
    await db.commit()
    old_id = artifact.id

    _patch_common(monkeypatch, service, integrations_service, artifact)
    _stub_drive(monkeypatch, google_drive, size=len(same_body), modified_time="REV-NEW")

    async def _download(*, access_token, file_id, export_mime, max_bytes):
        return same_body

    monkeypatch.setattr(google_drive, "download_drive_file", _download)

    result = await service.resync_artifact(db, contributor, framework.id, old_id)

    assert result.id == old_id
    row = await db.get(Artifact, old_id)
    assert row.source_synced_revision == "REV-NEW"
    assert row.processing_status == "processed"
    remaining = await db.scalars(
        select(Artifact).where(Artifact.framework_id == framework.id)
    )
    assert [a.id for a in remaining] == [old_id]


async def test_resync_noop_when_revision_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    source_preview_ctx: tuple,  # noqa: F811
):
    """An unchanged Drive revision short-circuits with already_up_to_date."""
    from app.integrations import google_drive
    from app.modules.frameworks import service
    from app.modules.integrations import service as integrations_service

    db, contributor, framework, artifact = source_preview_ctx
    artifact.processing_status = "processed"
    await db.commit()
    old_id = artifact.id

    _patch_common(monkeypatch, service, integrations_service, artifact)
    _stub_drive(
        monkeypatch, google_drive, size=1, modified_time=artifact.source_synced_revision
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.resync_artifact(db, contributor, framework.id, old_id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "already_up_to_date"


async def test_resync_blocked_while_processing_fresh_lease(
    monkeypatch: pytest.MonkeyPatch,
    source_preview_ctx: tuple,  # noqa: F811
):
    """A fresh processing lease blocks a competing re-sync with a 409."""
    from app.modules.frameworks import service
    from app.modules.integrations import service as integrations_service

    db, contributor, framework, artifact = source_preview_ctx
    artifact.processing_status = "processing"
    artifact.processing_started_at = datetime.now(UTC)
    await db.commit()
    old_id = artifact.id

    _patch_common(monkeypatch, service, integrations_service, artifact)

    with pytest.raises(HTTPException) as exc_info:
        await service.resync_artifact(db, contributor, framework.id, old_id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "artifact_processing"


async def test_resync_supersedes_stale_lease(
    monkeypatch: pytest.MonkeyPatch,
    source_preview_ctx: tuple,  # noqa: F811
):
    """A stale processing lease no longer blocks a re-sync; it forks instead."""
    from app.integrations import google_drive
    from app.modules.frameworks import service
    from app.modules.frameworks.models_artifact import Artifact
    from app.modules.integrations import service as integrations_service

    db, contributor, framework, artifact = source_preview_ctx
    artifact.processing_status = "processing"
    artifact.processing_started_at = datetime.now(UTC) - timedelta(minutes=31)
    artifact.content_sha256 = "OLD-HASH"
    await db.commit()
    old_id = artifact.id
    new_body = b"NEW-CONTENT-STALE"

    _patch_common(monkeypatch, service, integrations_service, artifact)
    _stub_drive(monkeypatch, google_drive, size=len(new_body), modified_time="REV-NEW")

    async def _download(*, access_token, file_id, export_mime, max_bytes):
        return new_body

    monkeypatch.setattr(google_drive, "download_drive_file", _download)

    result = await service.resync_artifact(db, contributor, framework.id, old_id)

    assert result.id != old_id
    new_row = await db.get(Artifact, result.id)
    assert new_row.current_for_framework is True


async def test_resync_source_gone_returns_409(
    monkeypatch: pytest.MonkeyPatch,
    source_preview_ctx: tuple,  # noqa: F811
):
    """A deleted/inaccessible source file 409s as source_unavailable."""
    from app.integrations import google_drive
    from app.integrations.google_drive import GoogleDriveNotFoundError
    from app.modules.frameworks import service
    from app.modules.integrations import service as integrations_service

    db, contributor, framework, artifact = source_preview_ctx
    artifact.processing_status = "processed"
    await db.commit()
    old_id = artifact.id

    _patch_common(monkeypatch, service, integrations_service, artifact)

    async def _meta(*, access_token, file_id):
        raise GoogleDriveNotFoundError("gone")

    monkeypatch.setattr(google_drive, "get_drive_file_metadata", _meta)

    with pytest.raises(HTTPException) as exc_info:
        await service.resync_artifact(db, contributor, framework.id, old_id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "source_unavailable"


async def test_resync_retains_version_referenced_old_row(
    monkeypatch: pytest.MonkeyPatch,
    source_preview_ctx: tuple,  # noqa: F811
):
    """An old row still referenced by a published version is retained, not deleted."""
    from app.integrations import google_drive
    from app.modules.frameworks import service
    from app.modules.frameworks.models import FrameworkVersion, FrameworkVersionArtifact
    from app.modules.frameworks.models_artifact import Artifact
    from app.modules.integrations import service as integrations_service

    db, contributor, framework, artifact = source_preview_ctx
    artifact.processing_status = "processed"
    artifact.content_sha256 = "OLD-HASH"
    await db.commit()
    old_id = artifact.id
    old_file_key = artifact.file_key
    new_body = b"NEW-CONTENT-RETAIN"

    version = FrameworkVersion(
        framework_id=framework.id,
        version="1.0.0",
        change_type="major",
        change_log="Initial version.",
    )
    db.add(version)
    await db.flush()
    db.add(
        FrameworkVersionArtifact(framework_version_id=version.id, artifact_id=old_id)
    )
    await db.commit()

    deleted_objects: list[str] = []
    _patch_common(monkeypatch, service, integrations_service, artifact)
    monkeypatch.setattr(
        service.s3.storage, "delete_object",
        lambda bucket, key: deleted_objects.append(key),
    )
    _stub_drive(monkeypatch, google_drive, size=len(new_body), modified_time="REV-NEW")

    async def _download(*, access_token, file_id, export_mime, max_bytes):
        return new_body

    monkeypatch.setattr(google_drive, "download_drive_file", _download)

    result = await service.resync_artifact(db, contributor, framework.id, old_id)

    assert result.id != old_id
    old_row = await db.get(Artifact, old_id)
    assert old_row is not None
    assert old_row.current_for_framework is False
    assert old_file_key not in deleted_objects


async def test_resync_repoints_preview_pointer(
    monkeypatch: pytest.MonkeyPatch,
    source_preview_ctx: tuple,  # noqa: F811
):
    """The framework's preview pointer follows the fork to the new artifact id."""
    from app.integrations import google_drive
    from app.modules.frameworks import service
    from app.modules.integrations import service as integrations_service

    db, contributor, framework, artifact = source_preview_ctx
    artifact.processing_status = "processed"
    artifact.content_sha256 = "OLD-HASH"
    framework.preview_artifact_id = artifact.id
    await db.commit()
    old_id = artifact.id
    new_body = b"NEW-CONTENT-PREVIEW"

    _patch_common(monkeypatch, service, integrations_service, artifact)
    _stub_drive(monkeypatch, google_drive, size=len(new_body), modified_time="REV-NEW")

    async def _download(*, access_token, file_id, export_mime, max_bytes):
        return new_body

    monkeypatch.setattr(google_drive, "download_drive_file", _download)

    result = await service.resync_artifact(db, contributor, framework.id, old_id)

    await db.refresh(framework)
    assert framework.preview_artifact_id == result.id


async def test_resync_forks_when_token_refresh_rolls_back_session(
    monkeypatch: pytest.MonkeyPatch,
    source_preview_ctx: tuple,  # noqa: F811
):
    """A token refresh that rolls the session back must not corrupt the fork.

    ``get_active_connection_with_fresh_token`` rolls the caller's transaction
    back when it refreshes an expiring token. Re-sync must fetch the token
    before it locks the artifact, so that rollback cannot release a held row
    lock mid check-then-fork. This reproduces the rollback and asserts the fork
    still completes cleanly.
    """
    from app.integrations import google_drive
    from app.modules.frameworks import service
    from app.modules.frameworks.models_artifact import Artifact
    from app.modules.integrations import service as integrations_service

    db, contributor, framework, artifact = source_preview_ctx
    artifact.processing_status = "processed"
    artifact.content_sha256 = "OLD-HASH"
    await db.commit()
    old_id = artifact.id
    new_body = b"REFRESHED-CONTENT"

    _patch_common(monkeypatch, service, integrations_service, artifact)

    async def _rollback_loader(db, *, user_id, connection_id):
        # Mimic the real helper refreshing an expiring token: it rolls the
        # caller's transaction back before returning the fresh token.
        from app.modules.integrations.models import OAuthConnection
        if db.in_transaction():
            await db.rollback()
        return (
            OAuthConnection(id=connection_id, user_id=user_id,
                            provider="google_drive", scopes="s", status="active"),
            "token",
        )

    monkeypatch.setattr(
        integrations_service,
        "get_active_connection_with_fresh_token",
        _rollback_loader,
    )
    _stub_drive(
        monkeypatch, google_drive, size=len(new_body), modified_time="REV-REFRESH"
    )

    async def _download(*, access_token, file_id, export_mime, max_bytes):
        return new_body

    monkeypatch.setattr(google_drive, "download_drive_file", _download)

    result = await service.resync_artifact(db, contributor, framework.id, old_id)

    assert result.id != old_id
    new_row = await db.get(Artifact, result.id)
    assert new_row.current_for_framework is True
    assert new_row.content_sha256 == hashlib.sha256(new_body).hexdigest()
    assert await db.get(Artifact, old_id) is None
