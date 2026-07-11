"""Integration tests for connector artifact re-bind (attach/repoint) and detach."""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest
import respx
from httpx import AsyncClient

from app.integrations import s3
from tests.integration.test_frameworks_crud import (
    _seed_drive_connection,
    auth_headers,
    create_artifact_for_framework,
    create_draft_framework,
    create_user_with_roles,
    framework_test_context,  # noqa: F401
    migrated_database,  # noqa: F401
)

pytestmark = pytest.mark.usefixtures("migrated_database", "framework_test_context")


def _patch_delete_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the fake artifact storage no-op delete hooks used by bind/detach cleanup."""
    monkeypatch.setattr(
        s3.storage, "delete_prefix", lambda bucket, prefix: None, raising=False
    )
    monkeypatch.setattr(
        s3.storage, "delete_object", lambda bucket, key: None, raising=False
    )


async def _create_upload_draft(
    client: AsyncClient, *, contributor_email: str
) -> tuple[UUID, str, str]:
    """Create a contributor, draft framework, and one plain upload artifact."""
    contributor_id = await create_user_with_roles(contributor_email, ["contributor"])
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client, contributor_id, framework_id
    )
    return contributor_id, framework_id, artifact_id


@pytest.mark.asyncio
async def test_bind_source_owner_attach_returns_new_bound_id(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owner attach on an upload draft artifact forks a new bound artifact id.

    Also asserts the confidentiality guarantee: the ArtifactResponse body must
    never leak raw source-binding columns to any caller, owner included.
    """
    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(lambda _: None)}),
    )
    _patch_delete_hooks(monkeypatch)
    contributor_id, framework_id, artifact_id = await _create_upload_draft(
        client, contributor_email="bind-owner@auracles.space"
    )
    connection_id = await _seed_drive_connection(contributor_id)

    with respx.mock as respx_mock:
        respx_mock.get("https://www.googleapis.com/drive/v3/files/file-A").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "file-A",
                    "name": "attached.pdf",
                    "mimeType": "application/pdf",
                    "size": "17",
                    "modifiedTime": "REV-A",
                },
            )
        )
        respx_mock.get(
            "https://www.googleapis.com/drive/v3/files/file-A",
            params__contains={"alt": "media"},
        ).mock(return_value=httpx.Response(200, content=b"attached content!"))
        response = await client.post(
            f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/bind-source",
            headers=auth_headers(contributor_id, ["contributor"]),
            json={"connection_id": str(connection_id), "file_id": "file-A"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] != artifact_id
    assert body["source_kind"] == "google_drive"

    # Confidentiality: raw source-binding columns are never serialized out.
    for forbidden_key in (
        "source_external_id",
        "source_connection_id",
        "source_synced_revision",
    ):
        assert forbidden_key not in body


@pytest.mark.asyncio
async def test_detach_reverts_bound_artifact_to_upload(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detaching a freshly bound artifact reverts it to a plain upload."""
    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(lambda _: None)}),
    )
    _patch_delete_hooks(monkeypatch)
    contributor_id, framework_id, artifact_id = await _create_upload_draft(
        client, contributor_email="detach-owner@auracles.space"
    )
    connection_id = await _seed_drive_connection(contributor_id)

    with respx.mock as respx_mock:
        respx_mock.get("https://www.googleapis.com/drive/v3/files/file-B").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "file-B",
                    "name": "attached.pdf",
                    "mimeType": "application/pdf",
                    "size": "17",
                    "modifiedTime": "REV-B",
                },
            )
        )
        respx_mock.get(
            "https://www.googleapis.com/drive/v3/files/file-B",
            params__contains={"alt": "media"},
        ).mock(return_value=httpx.Response(200, content=b"attached content!"))
        bind_response = await client.post(
            f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/bind-source",
            headers=auth_headers(contributor_id, ["contributor"]),
            json={"connection_id": str(connection_id), "file_id": "file-B"},
        )
    assert bind_response.status_code == 200
    bound_artifact_id = bind_response.json()["id"]

    detach_response = await client.delete(
        f"/v1/frameworks/{framework_id}/artifacts/{bound_artifact_id}/source",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert detach_response.status_code == 200
    assert detach_response.json()["source_kind"] == "upload"
    assert detach_response.json()["id"] == bound_artifact_id


@pytest.mark.asyncio
async def test_bind_source_non_owner_gets_404(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A contributor cannot bind a source onto another contributor's artifact."""
    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(lambda _: None)}),
    )
    _patch_delete_hooks(monkeypatch)
    contributor_id, framework_id, artifact_id = await _create_upload_draft(
        client, contributor_email="bind-owner-404@auracles.space"
    )
    other_id = await create_user_with_roles(
        "bind-other-404@auracles.space", ["contributor"]
    )
    connection_id = await _seed_drive_connection(contributor_id)

    response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/bind-source",
        headers=auth_headers(other_id, ["contributor"]),
        json={"connection_id": str(connection_id), "file_id": "file-A"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_bind_source_foreign_connection_gets_404(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Binding with another user's connection id is refused as not found."""
    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(lambda _: None)}),
    )
    _patch_delete_hooks(monkeypatch)
    contributor_id, framework_id, artifact_id = await _create_upload_draft(
        client, contributor_email="bind-owner-foreign@auracles.space"
    )
    other_id = await create_user_with_roles(
        "bind-other-foreign@auracles.space", ["contributor"]
    )
    foreign_connection_id = await _seed_drive_connection(other_id)

    response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/bind-source",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={"connection_id": str(foreign_connection_id), "file_id": "file-A"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_detach_non_owner_gets_404(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A contributor cannot detach another contributor's artifact source."""
    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(lambda _: None)}),
    )
    _patch_delete_hooks(monkeypatch)
    contributor_id, framework_id, artifact_id = await _create_upload_draft(
        client, contributor_email="detach-owner-404@auracles.space"
    )
    other_id = await create_user_with_roles(
        "detach-other-404@auracles.space", ["contributor"]
    )

    response = await client.delete(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/source",
        headers=auth_headers(other_id, ["contributor"]),
    )

    assert response.status_code == 404
