"""Integration tests for the connector artifact re-sync endpoint."""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest
import respx
from httpx import AsyncClient

from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from tests.integration.test_frameworks_crud import (
    auth_headers,
    create_artifact_for_framework,
    create_draft_framework,
    create_user_with_roles,
    framework_test_context,  # noqa: F401
    migrated_database,  # noqa: F401
)
from tests.integration.test_frameworks_source_preview import (
    _create_drive_bound_artifact,
)

pytestmark = pytest.mark.usefixtures("migrated_database", "framework_test_context")


async def _mark_processed(artifact_id: str) -> None:
    """Fast-forward a freshly imported artifact past its processing lease.

    The real pipeline runs via a faked Celery task in these tests, so the row
    stays ``processing`` forever unless nudged — that would otherwise trip
    re-sync's in-flight guard before the re-sync behavior under test runs.
    """
    async with async_session_factory() as session:
        artifact = await session.get(Artifact, UUID(artifact_id))
        assert artifact is not None
        artifact.processing_status = "processed"
        await session.commit()


def _patch_delete_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the fake artifact storage no-op delete hooks used by re-sync cleanup."""
    monkeypatch.setattr(
        s3.storage, "delete_prefix", lambda bucket, prefix: None, raising=False
    )
    monkeypatch.setattr(
        s3.storage, "delete_object", lambda bucket, key: None, raising=False
    )


@pytest.mark.asyncio
async def test_resync_owner_drifted_artifact_forks_and_retires_old_id(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A drifted source forks a new artifact id; the old id 404s afterward."""
    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(lambda _: None)}),
    )
    _patch_delete_hooks(monkeypatch)
    contributor_id, framework_id, old_artifact_id = await _create_drive_bound_artifact(
        client,
        contributor_email="resync-owner@auracles.space",
    )
    await _mark_processed(old_artifact_id)

    with respx.mock as respx_mock:
        respx_mock.get("https://www.googleapis.com/drive/v3/files/file-1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "file-1",
                    "name": "brief.pdf",
                    "mimeType": "application/pdf",
                    "size": "20",
                    "modifiedTime": "REV-NEW",
                },
            )
        )
        respx_mock.get(
            "https://www.googleapis.com/drive/v3/files/file-1",
            params__contains={"alt": "media"},
        ).mock(return_value=httpx.Response(200, content=b"resynced content!!!!"))
        response = await client.post(
            f"/v1/frameworks/{framework_id}/artifacts/{old_artifact_id}/resync",
            headers=auth_headers(contributor_id, ["contributor"]),
        )

    assert response.status_code == 200
    new_artifact_id = response.json()["id"]
    assert new_artifact_id != old_artifact_id

    list_response = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts",
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    listed_ids = {item["id"] for item in list_response.json()}
    assert new_artifact_id in listed_ids
    assert old_artifact_id not in listed_ids

    # The retired id no longer resolves as a current, source-bound artifact.
    preview_response = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts/{old_artifact_id}/source-preview",
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    assert preview_response.status_code == 404


@pytest.mark.asyncio
async def test_resync_non_owner_gets_404(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A contributor cannot re-sync another contributor's artifact."""
    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(lambda _: None)}),
    )
    _patch_delete_hooks(monkeypatch)
    _, framework_id, artifact_id = await _create_drive_bound_artifact(
        client,
        contributor_email="resync-owner-404@auracles.space",
    )
    other_id = await create_user_with_roles(
        "resync-other@auracles.space",
        ["contributor"],
    )

    response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/resync",
        headers=auth_headers(other_id, ["contributor"]),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_resync_published_framework_conflicts(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Published frameworks are no longer pre-publish, so re-sync is refused."""
    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(lambda _: None)}),
    )
    _patch_delete_hooks(monkeypatch)
    contributor_id, framework_id, artifact_id = await _create_drive_bound_artifact(
        client,
        contributor_email="resync-published@auracles.space",
    )

    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "published"
        await session.commit()

    response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/resync",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_resync_upload_artifact_returns_404(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An artifact with no bound connector source cannot be re-synced."""
    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(lambda _: None)}),
    )
    contributor_id = await create_user_with_roles(
        "resync-upload-owner@auracles.space", ["contributor"]
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client, contributor_id, framework_id
    )

    response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/resync",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 404
