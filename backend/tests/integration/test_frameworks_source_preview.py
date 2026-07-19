"""Integration tests for the owner-only framework source-preview endpoint."""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest
import respx
from httpx import AsyncClient

from app.core.database import async_session_factory
from app.integrations import google_drive, s3
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from tests.integration.test_frameworks_crud import (
    _seed_drive_connection,
    auth_headers,
    create_draft_framework,
    create_user_with_roles,
    framework_test_context,  # noqa: F401
    mark_artifact_pipeline_state,
    migrated_database,  # noqa: F401
)

pytestmark = pytest.mark.usefixtures("migrated_database", "framework_test_context")


async def _create_drive_bound_artifact(
    client: AsyncClient,
    *,
    contributor_email: str,
) -> tuple[UUID, str, str]:
    """Create a contributor, draft framework, and imported Drive artifact."""
    contributor_id = await create_user_with_roles(
        contributor_email,
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    connection_id = await _seed_drive_connection(contributor_id)

    with respx.mock as respx_mock:
        respx_mock.get("https://www.googleapis.com/drive/v3/files/file-1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "file-1",
                    "name": "brief.pdf",
                    "mimeType": "application/pdf",
                    "size": "13",
                    "modifiedTime": "REV-OLD",
                },
            )
        )
        respx_mock.get(
            "https://www.googleapis.com/drive/v3/files/file-1",
            params__contains={"alt": "media"},
        ).mock(return_value=httpx.Response(200, content=b"dummy content"))
        import_response = await client.post(
            f"/v1/frameworks/{framework_id}/artifacts/from-connector",
            headers=auth_headers(contributor_id, ["contributor"]),
            json={"connection_id": str(connection_id), "file_id": "file-1"},
        )

    assert import_response.status_code == 200
    return contributor_id, framework_id, str(import_response.json()["id"])


@pytest.mark.asyncio
async def test_source_preview_owner_draft_returns_flags(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The owner of a draft Drive artifact gets preview_url and drift flags."""
    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(lambda _: None)}),
    )
    contributor_id, framework_id, artifact_id = await _create_drive_bound_artifact(
        client,
        contributor_email="preview-owner-endpoint@auracles.space",
    )

    async def _state(*, access_token: str, file_id: str) -> tuple[str, str | None]:
        """Report a newer Drive revision and a thumbnail link."""
        return "REV-NEW", "https://lh3.googleusercontent.com/t.png"

    async def _thumb(
        *, thumbnail_link: str, access_token: str, max_bytes: int
    ) -> bytes:
        """Return the thumbnail payload served through the backend."""
        return b"PNGDATA"

    exists_calls: list[str] = []

    def _object_exists(bucket: str, key: str) -> bool:
        """Miss once, then confirm the cached object exists."""
        exists_calls.append(key)
        return len(exists_calls) > 1

    monkeypatch.setattr(google_drive, "fetch_drive_source_state", _state, raising=False)
    monkeypatch.setattr(google_drive, "download_drive_thumbnail", _thumb)
    monkeypatch.setattr(s3.storage, "object_exists", _object_exists)
    monkeypatch.setattr(
        s3.storage,
        "upload_bytes",
        lambda bucket, key, body, mime_type: None,
    )
    monkeypatch.setattr(
        s3.storage,
        "delete_prefix",
        lambda bucket, prefix: None,
        raising=False,
    )
    monkeypatch.setattr(
        s3.storage,
        "presigned_get",
        lambda bucket, key, expires_in: "https://s3/presigned",
        raising=False,
    )

    response = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/source-preview",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 200
    assert response.json() == {
        "preview_url": "https://s3/presigned",
        "source_updated": True,
        "source_last_synced_at": response.json()["source_last_synced_at"],
    }

    async with async_session_factory() as session:
        artifact = await session.get(Artifact, UUID(artifact_id))
    assert artifact is not None
    assert artifact.source_synced_revision == "REV-OLD"


@pytest.mark.asyncio
async def test_source_preview_non_owner_gets_404(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A contributor cannot read another contributor's source preview."""
    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(lambda _: None)}),
    )
    _, framework_id, artifact_id = await _create_drive_bound_artifact(
        client,
        contributor_email="preview-owner-404@auracles.space",
    )
    other_id = await create_user_with_roles(
        "preview-other@auracles.space",
        ["contributor"],
    )

    response = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/source-preview",
        headers=auth_headers(other_id, ["contributor"]),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_source_preview_published_framework_conflicts(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Published frameworks are no longer pre-publish, so preview is refused."""
    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(lambda _: None)}),
    )
    contributor_id, framework_id, artifact_id = await _create_drive_bound_artifact(
        client,
        contributor_email="preview-published@auracles.space",
    )

    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "published"
        await session.commit()

    response = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/source-preview",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_publish_deletes_source_preview_objects(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publishing removes draft-only source-preview cache objects."""
    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(lambda _: None)}),
    )
    deleted_prefixes: list[str] = []

    class FakeNotifyTask:
        """Notification task double for publish tests."""

        def delay(self, framework_id: str, new_version: str) -> None:
            """Do nothing for publish notifications in tests."""

    async def _index_framework_artifacts(framework_id: UUID) -> None:
        """Skip external index writes in the publish test."""

    monkeypatch.setattr(
        "app.modules.frameworks.service.index_framework_artifacts",
        _index_framework_artifacts,
        raising=False,
    )
    monkeypatch.setattr(
        "app.modules.frameworks.service.notify_licensees_of_new_version",
        FakeNotifyTask(),
        raising=False,
    )
    monkeypatch.setattr(
        s3.storage,
        "delete_prefix",
        lambda bucket, prefix: deleted_prefixes.append(prefix),
        raising=False,
    )

    contributor_id, framework_id, artifact_id = await _create_drive_bound_artifact(
        client,
        contributor_email="preview-publish-cleanup@auracles.space",
    )
    await mark_artifact_pipeline_state(framework_id, artifact_id)
    # Publish requires a preview when a file is eligible; select one while draft.
    await client.patch(
        f"/v1/frameworks/{framework_id}/preview-artifact",
        json={"artifact_id": artifact_id},
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    submitted = await client.post(
        f"/v1/frameworks/{framework_id}/submit",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    published = await client.post(
        f"/v1/frameworks/{framework_id}/publish",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert submitted.status_code == 200
    assert published.status_code == 200
    assert (
        f"frameworks/{framework_id}/artifacts/{artifact_id}/source-preview/"
        in deleted_prefixes
    )

    async with async_session_factory() as session:
        artifact = await session.get(Artifact, UUID(artifact_id))
    assert artifact is not None
    assert artifact.source_kind == "google_drive"
    assert artifact.source_external_id == "file-1"
