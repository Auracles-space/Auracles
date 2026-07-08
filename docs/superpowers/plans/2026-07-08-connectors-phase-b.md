# Connectors Phase B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist per-artifact source binding and give contributors a draft-only, owner-only live Drive-thumbnail preview with a "Source updated since import" drift badge — without moving any new bytes or weakening a single marketplace invariant.

**Architecture:** Additive `source_*` columns on `artifacts` stamped at import; a dedicated owner-only pre-publish endpoint fetches the current Drive `modifiedTime` + `thumbnailLink` server-side (token never leaves backend), caches the thumbnail to our S3 under a `modifiedTime`-versioned key, and returns a presigned URL plus a `source_updated` flag. The preview lives in its own response schema so it is structurally impossible to leak onto public/buyer surfaces. Account deletion now revokes + purges connector grants.

**Tech Stack:** FastAPI (Python 3.13), SQLAlchemy async, Alembic, Pydantic v2, boto3 (S3), httpx (Drive), pytest + httpx AsyncClient; Next.js 15 + Tailwind, vitest + @testing-library/react + msw; `@hey-api/openapi-ts` codegen.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-08-connectors-phase-b-design.md` — the seven locked decisions govern; do not reopen.
- **No `Co-Authored-By` / no Claude trailer** in commit messages — end at the last meaningful line.
- **Work on `main`** — do not create a branch.
- **Repo is npm, not pnpm** (frontend).
- **Copy-in unchanged:** every artifact still owns its bytes from import; `Artifact.file_key`/`file_size` stay `NOT NULL`. Phase B moves **no** new bytes.
- **Preview is display-only, draft-only, owner-only.** Never on `ArtifactResponse` or any public/catalog/buyer serializer. Never for `source_kind='upload'` artifacts.
- **Tokens** Fernet-encrypted at rest, server-side only, never returned in a response, never logged.
- **SSRF:** the only new external fetch is the thumbnail; allowlist the `thumbnailLink` host before the GET and size-cap the fetch.
- **Preview never writes `source_last_synced_at` / `source_synced_revision`** (those move only on byte sync: import in B, resync in C).
- Migration additive + reversible: `alembic upgrade head` and `alembic downgrade -1` both succeed.
- Backend commands run from `backend/`: `uv run pytest <path> -v`, `uv run alembic upgrade head`, `uv run alembic downgrade -1`, `uv run ruff check .`, `uv run mypy app`. Frontend from `frontend/`: `npm run typecheck`, `npm run lint`, `npx vitest run <path>`, `npm run generate:api`.

## File Structure

| File | Responsibility | Task |
|------|----------------|------|
| `backend/migrations/versions/2026_07_08_0069_artifact_source_binding.py` | Add 5 `source_*` columns to `artifacts` | 1 |
| `backend/app/modules/frameworks/models_artifact.py` | ORM mapping for the 5 columns | 1 |
| `backend/app/integrations/google_drive.py` | `modifiedTime` in metadata fields; `fetch_drive_source_state`; `download_drive_thumbnail` + host allowlist; `quote()` file_id/folder_id | 1, 2, 4 |
| `backend/app/modules/frameworks/service.py` | Stamp binding at import; `get_source_preview`; publish cleanup | 1, 2, 3 |
| `backend/app/modules/frameworks/schemas.py` | `SourcePreviewResponse` | 2 |
| `backend/app/modules/frameworks/router.py` | `GET …/source-preview` endpoint | 2 |
| `backend/app/integrations/s3.py` | `delete_prefix` helper | 2 |
| `backend/app/modules/gdpr/anonymise.py` | Revoke + delete `oauth_connections` | 4 |
| `contracts/openapi.yaml` + `frontend/src/lib/generated/*` | Contract + regenerated client | 5 |
| `frontend/src/components/modules/frameworks/source-preview-badge.tsx` | Draft thumbnail + "Source updated" badge | 5 |
| `frontend/src/components/modules/frameworks/artifact-manifest.tsx` | Mount the badge per google_drive draft artifact | 5 |

---

### Task 1: Source-binding columns + stamp at import

**Files:**
- Create: `backend/migrations/versions/2026_07_08_0069_artifact_source_binding.py`
- Modify: `backend/app/modules/frameworks/models_artifact.py` (add 5 mapped columns after `mime_type`)
- Modify: `backend/app/integrations/google_drive.py:349-371` (`get_drive_file_metadata` fields)
- Modify: `backend/app/modules/frameworks/service.py:978-1150` (`import_artifact_from_connector` stamps binding)
- Test: `backend/tests/unit/test_google_drive_integration.py`, `backend/tests/integration/test_integrations_files.py`

**Interfaces:**
- Consumes: `get_active_connection_with_fresh_token(db, *, user_id, connection_id=...) -> tuple[OAuthConnection, str]` (integrations service); `get_drive_file_metadata(*, access_token, file_id) -> dict` (returns Drive `files.get` JSON).
- Produces: `Artifact.source_kind: str`, `Artifact.source_external_id: str | None`, `Artifact.source_connection_id: UUID | None`, `Artifact.source_last_synced_at: datetime | None`, `Artifact.source_synced_revision: str | None`. `get_drive_file_metadata` JSON now includes `modifiedTime`.

- [ ] **Step 1: Write the failing test — metadata carries modifiedTime**

Add to `backend/tests/unit/test_google_drive_integration.py`:

```python
@pytest.mark.asyncio
async def test_get_drive_file_metadata_requests_modified_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_drive_file_metadata must request modifiedTime so import can stamp the drift baseline."""
    captured: dict[str, object] = {}

    class _Resp:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"id": "f1", "name": "n", "mimeType": "application/pdf", "size": "10", "modifiedTime": "2026-07-08T00:00:00Z"}

    class _Client:
        def __init__(self, *a: object, **k: object) -> None: ...
        async def __aenter__(self) -> "_Client": return self
        async def __aexit__(self, *a: object) -> None: ...
        async def get(self, url: str, params: dict[str, str], headers: dict[str, str]) -> _Resp:
            captured["fields"] = params["fields"]
            return _Resp()

    monkeypatch.setattr("app.integrations.google_drive.httpx.AsyncClient", _Client)
    from app.integrations.google_drive import get_drive_file_metadata

    result = await get_drive_file_metadata(access_token="t", file_id="f1")
    assert "modifiedTime" in str(captured["fields"])
    assert result["modifiedTime"] == "2026-07-08T00:00:00Z"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_google_drive_integration.py::test_get_drive_file_metadata_requests_modified_time -v`
Expected: FAIL — `fields` currently `"id,name,mimeType,size"`, assertion on `modifiedTime` fails.

- [ ] **Step 3: Add modifiedTime to the fields set**

In `backend/app/integrations/google_drive.py`, `get_drive_file_metadata`, change the params fields:

```python
                params={"fields": "id,name,mimeType,size,modifiedTime"},
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_google_drive_integration.py::test_get_drive_file_metadata_requests_modified_time -v`
Expected: PASS

- [ ] **Step 5: Add the ORM columns**

In `backend/app/modules/frameworks/models_artifact.py`, immediately after the `mime_type` column, add:

```python
    # Source binding (Connectors Phase B). Records where the artifact's bytes
    # came from so a later version can pull again. `upload` for direct uploads
    # and legacy/Phase-A imports (no source recorded); `google_drive` for
    # connector imports. `source_synced_revision` is the provider modifiedTime
    # captured at the last byte sync — the drift baseline the preview compares.
    source_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'upload'")
    )
    source_external_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_connection_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("oauth_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_synced_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

Ensure the module imports exist at the top (add any missing): `from datetime import datetime`, `from sqlalchemy import DateTime, ForeignKey, String, text`, `from sqlalchemy.dialects.postgresql import UUID as PG_UUID`, `from uuid import UUID`.

- [ ] **Step 6: Write the migration**

Create `backend/migrations/versions/2026_07_08_0069_artifact_source_binding.py`:

```python
"""Add source-binding columns to artifacts for Connectors Phase B.

Supports the draft live-mirror preview + source binding
(docs/superpowers/plans/2026-07-08-connectors-phase-b.md, Task 1). Additive and
backwards-compatible: every existing artifact (real uploads and Phase-A
connector imports alike) defaults to source_kind='upload', so legacy rows keep
their exact prior behaviour and record no external source to mirror.

Revision ID: 2026_07_08_0069
Revises: 2026_07_06_0068
Create Date: 2026-07-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_08_0069"
down_revision: str | None = "2026_07_06_0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "artifacts",
        sa.Column(
            "source_kind",
            sa.String(length=20),
            nullable=False,
            server_default="upload",
        ),
    )
    op.add_column(
        "artifacts",
        sa.Column("source_external_id", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "artifacts",
        sa.Column("source_connection_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "artifacts",
        sa.Column("source_last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "artifacts",
        sa.Column("source_synced_revision", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_artifacts_source_connection_id",
        "artifacts",
        "oauth_connections",
        ["source_connection_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_artifacts_source_connection_id", "artifacts", type_="foreignkey"
    )
    op.drop_column("artifacts", "source_synced_revision")
    op.drop_column("artifacts", "source_last_synced_at")
    op.drop_column("artifacts", "source_connection_id")
    op.drop_column("artifacts", "source_external_id")
    op.drop_column("artifacts", "source_kind")
```

- [ ] **Step 7: Run the migration up and down**

Run: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: all three succeed; no errors. (This leaves the DB at head for the next steps.)

- [ ] **Step 8: Write the failing test — import stamps the binding**

Add to `backend/tests/integration/test_integrations_files.py` (reuse that file's existing fixtures for an authenticated contributor with an active connection; follow the pattern already there for a successful `from-connector` import). The assertion:

```python
@pytest.mark.asyncio
async def test_from_connector_stamps_source_binding(
    connected_contributor_client, connected_connection_id, drive_file_stub, db_session
) -> None:
    """Importing from Drive stamps source_kind='google_drive' and the drift baseline.

    drive_file_stub patches get_drive_file_metadata/download to return a pdf
    named 'brief.pdf' with modifiedTime '2026-07-08T00:00:00Z'.
    """
    framework_id = await _create_draft_framework(connected_contributor_client)
    resp = await connected_contributor_client.post(
        f"/v1/frameworks/{framework_id}/artifacts/from-connector",
        json={"connection_id": str(connected_connection_id), "file_id": "f1"},
    )
    assert resp.status_code == 201
    artifact_id = resp.json()["id"]

    from app.modules.frameworks.models_artifact import Artifact
    artifact = await db_session.get(Artifact, UUID(artifact_id))
    assert artifact.source_kind == "google_drive"
    assert artifact.source_external_id == "f1"
    assert str(artifact.source_connection_id) == str(connected_connection_id)
    assert artifact.source_synced_revision == "2026-07-08T00:00:00Z"
    assert artifact.source_last_synced_at is not None
```

If the file lacks helpers named `connected_contributor_client` / `connected_connection_id` / `drive_file_stub` / `_create_draft_framework`, reuse whatever the existing passing `from-connector` test in this file already uses to reach a successful import, and assert the same six fields on the resulting `Artifact` row.

- [ ] **Step 9: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_integrations_files.py::test_from_connector_stamps_source_binding -v`
Expected: FAIL — `source_kind` is the default `'upload'`, `source_external_id` is `None`.

- [ ] **Step 10: Stamp the binding at import**

In `backend/app/modules/frameworks/service.py`, `import_artifact_from_connector`, locate the `Artifact(...)` construction (around line 1119) and add the source fields. The `metadata` dict from `get_drive_file_metadata` now carries `modifiedTime`:

```python
    artifact = Artifact(
        id=artifact_id,
        framework_id=framework.id,
        name=filename,
        file_key=file_key,
        file_size=len(body),
        mime_type=effective_mime,
        processing_status="processing",
        source_kind="google_drive",
        source_external_id=payload.file_id,
        source_connection_id=connection.id,
        source_last_synced_at=datetime.now(UTC),
        source_synced_revision=str(metadata.get("modifiedTime")) if metadata.get("modifiedTime") else None,
    )
```

Confirm `from datetime import UTC, datetime` is imported in `service.py` (it is used elsewhere in the file). `connection` is the object returned by `get_active_connection_with_fresh_token` earlier in the function.

- [ ] **Step 11: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_integrations_files.py::test_from_connector_stamps_source_binding tests/unit/test_google_drive_integration.py -v`
Expected: PASS

- [ ] **Step 12: Lint + typecheck**

Run: `cd backend && uv run ruff check app/modules/frameworks app/integrations migrations && uv run mypy app/modules/frameworks app/integrations`
Expected: clean.

- [ ] **Step 13: Commit**

```bash
git add backend/migrations/versions/2026_07_08_0069_artifact_source_binding.py backend/app/modules/frameworks/models_artifact.py backend/app/integrations/google_drive.py backend/app/modules/frameworks/service.py backend/tests/unit/test_google_drive_integration.py backend/tests/integration/test_integrations_files.py
git commit -m "Add artifact source-binding columns and stamp them on connector import"
```

---

### Task 2: Source-preview endpoint + thumbnail cache-to-S3

**Files:**
- Modify: `backend/app/integrations/google_drive.py` (add `fetch_drive_source_state`, `download_drive_thumbnail`, `THUMBNAIL_ALLOWED_HOST_SUFFIXES`)
- Modify: `backend/app/integrations/s3.py` (add `delete_prefix`)
- Modify: `backend/app/modules/frameworks/schemas.py` (add `SourcePreviewResponse`)
- Modify: `backend/app/modules/frameworks/service.py` (add `get_source_preview`)
- Modify: `backend/app/modules/frameworks/router.py` (add GET endpoint)
- Test: `backend/tests/unit/test_google_drive_integration.py`, `backend/tests/unit/modules/test_frameworks_source_preview.py` (new), `backend/tests/integration/test_frameworks_source_preview.py` (new)

**Interfaces:**
- Consumes: `get_active_connection_with_fresh_token`, `_load_owned_framework(db, contributor, framework_id) -> Framework`, `_require_editable_artifacts(framework) -> None` (raises 409 unless status ∈ {draft, pipeline_failed, pipeline_passed}), `s3.storage.object_exists/upload_bytes/delete_object/presigned_get`, `get_settings().s3_artifacts_bucket`.
- Produces: `fetch_drive_source_state(*, access_token, file_id) -> tuple[str, str | None]` (returns `(modified_time, thumbnail_link_or_none)`); `download_drive_thumbnail(*, thumbnail_link, access_token, max_bytes) -> bytes`; `get_source_preview(db, contributor, framework_id, artifact_id) -> SourcePreviewResponse`; `SourcePreviewResponse{preview_url: str | None, source_updated: bool, source_last_synced_at: datetime | None}`; `S3Storage.delete_prefix(bucket, prefix) -> None`.

- [ ] **Step 1: Write the failing test — thumbnail host allowlist**

Add to `backend/tests/unit/test_google_drive_integration.py`:

```python
@pytest.mark.asyncio
async def test_download_drive_thumbnail_rejects_foreign_host() -> None:
    """A thumbnailLink pointing off Google's hosts must never be fetched (SSRF guard)."""
    from app.integrations.google_drive import download_drive_thumbnail, GoogleDriveError

    with pytest.raises(GoogleDriveError):
        await download_drive_thumbnail(
            thumbnail_link="https://evil.example.com/x.png",
            access_token="t",
            max_bytes=1024,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_google_drive_integration.py::test_download_drive_thumbnail_rejects_foreign_host -v`
Expected: FAIL — function does not exist.

- [ ] **Step 3: Add source-state + thumbnail helpers with allowlist**

In `backend/app/integrations/google_drive.py`, add near the top constants:

```python
# Hosts a Drive thumbnailLink may legitimately point at. The link comes from a
# provider response, so its host is validated before any fetch — closing a
# provider-response-driven SSRF. Suffix match so subdomains (lh3, lh4, …) pass.
THUMBNAIL_ALLOWED_HOST_SUFFIXES = (".googleusercontent.com", ".google.com")
_THUMBNAIL_TIMEOUT_SECONDS = 15.0
```

Add the functions:

```python
async def fetch_drive_source_state(
    *,
    access_token: str,
    file_id: str,
) -> tuple[str, str | None]:
    """Return (modifiedTime, thumbnailLink|None) for a Drive file.

    Used by the draft preview: modifiedTime drives the drift badge and the
    thumbnail cache key; thumbnailLink is the (short-lived, auth-bound) image URL.

    Raises:
        GoogleDriveAuthError: On 401/403 from Drive.
        GoogleDriveError: On other failures.
    """
    from urllib.parse import quote

    try:
        async with httpx.AsyncClient(timeout=_DRIVE_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{DRIVE_API_BASE}/files/{quote(file_id, safe='')}",
                params={"fields": "modifiedTime,thumbnailLink"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.HTTPError as exc:
        raise GoogleDriveError("Google Drive unreachable.") from exc
    if response.status_code >= 400:
        _raise_for_drive_response(response, action="fetch_drive_source_state")
    payload = response.json()
    modified_time = str(payload.get("modifiedTime", ""))
    thumbnail_link = payload.get("thumbnailLink")
    return modified_time, (str(thumbnail_link) if thumbnail_link else None)


def _thumbnail_host_allowed(thumbnail_link: str) -> bool:
    """Whether a thumbnailLink host is on the Google allowlist."""
    from urllib.parse import urlsplit

    host = urlsplit(thumbnail_link).hostname or ""
    return any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in THUMBNAIL_ALLOWED_HOST_SUFFIXES)


async def download_drive_thumbnail(
    *,
    thumbnail_link: str,
    access_token: str,
    max_bytes: int,
) -> bytes:
    """Fetch a Drive thumbnail image within a byte budget, host-allowlisted.

    Raises:
        GoogleDriveError: If the host is not allowlisted or the fetch fails.
        DriveFileTooLargeError: If the stream exceeds ``max_bytes``.
    """
    if not _thumbnail_host_allowed(thumbnail_link):
        logger.bind(module="integrations", action="download_drive_thumbnail").warning(
            "thumbnail_host_rejected"
        )
        raise GoogleDriveError("Thumbnail host is not allowed.")
    chunks: list[bytes] = []
    received = 0
    try:
        async with (
            httpx.AsyncClient(timeout=_THUMBNAIL_TIMEOUT_SECONDS) as client,
            client.stream(
                "GET",
                thumbnail_link,
                headers={"Authorization": f"Bearer {access_token}"},
            ) as response,
        ):
            if response.status_code >= 400:
                await response.aread()
                raise GoogleDriveError("Thumbnail fetch failed.")
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                if received > max_bytes:
                    raise DriveFileTooLargeError("Thumbnail exceeds the byte budget.")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise GoogleDriveError("Google thumbnail unreachable.") from exc
    return b"".join(chunks)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_google_drive_integration.py::test_download_drive_thumbnail_rejects_foreign_host -v`
Expected: PASS

- [ ] **Step 5: Add the S3 prefix-delete helper + its test**

Add to `backend/tests/unit/test_s3_storage.py` (create if absent) a test using a stubbed boto client, OR — matching the repo's existing S3 test approach — add a focused test that `delete_prefix` lists then deletes. Minimal test:

```python
def test_delete_prefix_deletes_listed_objects(monkeypatch) -> None:
    """delete_prefix removes every object under a prefix."""
    from app.integrations.s3 import S3Storage

    deleted: list[str] = []

    class _Client:
        def get_paginator(self, _op: str):
            class _P:
                def paginate(self, Bucket, Prefix):
                    yield {"Contents": [{"Key": f"{Prefix}a.png"}, {"Key": f"{Prefix}b.png"}]}
            return _P()

        def delete_object(self, Bucket, Key):
            deleted.append(Key)

    storage = S3Storage.__new__(S3Storage)
    storage._client = _Client()  # type: ignore[attr-defined]
    storage.delete_prefix("bucket", "frameworks/x/artifacts/y/source-preview/")
    assert deleted == [
        "frameworks/x/artifacts/y/source-preview/a.png",
        "frameworks/x/artifacts/y/source-preview/b.png",
    ]
```

Run: `cd backend && uv run pytest tests/unit/test_s3_storage.py::test_delete_prefix_deletes_listed_objects -v`
Expected: FAIL — `delete_prefix` does not exist.

- [ ] **Step 6: Implement `delete_prefix`**

In `backend/app/integrations/s3.py`, add to `S3Storage` (after `delete_object`):

```python
    def delete_prefix(self, bucket: str, prefix: str) -> None:
        """Delete every private S3 object under a key prefix."""
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                self._client.delete_object(Bucket=bucket, Key=obj["Key"])
```

Run: `cd backend && uv run pytest tests/unit/test_s3_storage.py::test_delete_prefix_deletes_listed_objects -v`
Expected: PASS

- [ ] **Step 7: Add the response schema**

In `backend/app/modules/frameworks/schemas.py`, add (near `ArtifactResponse`):

```python
class SourcePreviewResponse(BaseModel):
    """Owner-only, draft-only live-mirror preview for a connector-bound artifact.

    Deliberately a separate schema from ArtifactResponse: the preview URL and
    drift flag must never ride on any public/catalog/buyer serializer, so they
    are structurally confined to this response, produced only by the owner-only
    pre-publish endpoint.
    """

    model_config = ConfigDict(from_attributes=True)

    preview_url: str | None
    source_updated: bool
    source_last_synced_at: datetime | None
```

Confirm `from pydantic import BaseModel, ConfigDict` and `from datetime import datetime` are imported in this file (they are used elsewhere).

- [ ] **Step 8: Write the failing service test**

Create `backend/tests/unit/modules/test_frameworks_source_preview.py`:

```python
"""Unit tests for the draft source-preview service (Connectors Phase B)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.frameworks import service


@pytest.mark.asyncio
async def test_source_preview_reports_updated_when_revision_changed(monkeypatch, source_preview_ctx) -> None:
    """source_updated is True when the live modifiedTime differs from the stored baseline.

    source_preview_ctx provides a draft framework owned by the contributor with a
    google_drive artifact whose source_synced_revision='REV-OLD', plus an active
    connection. It patches fetch_drive_source_state -> ('REV-NEW', 'https://lh3.googleusercontent.com/t.png')
    and stubs s3 object_exists -> False so a fetch+cache path runs.
    """
    db, contributor, framework, artifact = source_preview_ctx

    monkeypatch.setattr(
        service, "get_active_connection_with_fresh_token",
        _fake_connection(artifact.source_connection_id),
    )
    from app.integrations import google_drive
    async def _state(*, access_token, file_id):
        return "REV-NEW", "https://lh3.googleusercontent.com/t.png"
    async def _thumb(*, thumbnail_link, access_token, max_bytes):
        return b"PNGDATA"
    monkeypatch.setattr(google_drive, "fetch_drive_source_state", _state)
    monkeypatch.setattr(google_drive, "download_drive_thumbnail", _thumb)
    monkeypatch.setattr(service.s3.storage, "object_exists", lambda bucket, key: False)
    monkeypatch.setattr(service.s3.storage, "upload_bytes", lambda **k: None)
    monkeypatch.setattr(service.s3.storage, "delete_prefix", lambda bucket, prefix: None)
    monkeypatch.setattr(service.s3.storage, "presigned_get", lambda *a, **k: "https://s3/presigned")

    result = await service.get_source_preview(db, contributor, framework.id, artifact.id)

    assert result.source_updated is True
    assert result.preview_url == "https://s3/presigned"


@pytest.mark.asyncio
async def test_source_preview_refuses_upload_artifact(source_preview_ctx_upload) -> None:
    """An upload-kind artifact has no source to mirror -> 404."""
    from fastapi import HTTPException
    db, contributor, framework, artifact = source_preview_ctx_upload
    with pytest.raises(HTTPException) as exc:
        await service.get_source_preview(db, contributor, framework.id, artifact.id)
    assert exc.value.status_code == 404
```

Provide the `source_preview_ctx` / `source_preview_ctx_upload` fixtures and the `_fake_connection` helper in the same file, building rows with the project's `factory_boy` factories under `backend/tests/factories/` (Framework in `draft` status owned by the contributor; Artifact with `source_kind='google_drive'`, `source_synced_revision='REV-OLD'`, `source_connection_id` set; and a second one with `source_kind='upload'`). Follow the fixture style in `backend/tests/unit/modules/` for building an `AsyncSession` and factory rows.

- [ ] **Step 9: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_frameworks_source_preview.py -v`
Expected: FAIL — `service.get_source_preview` does not exist.

- [ ] **Step 10: Implement `get_source_preview`**

In `backend/app/modules/frameworks/service.py`, add (import the integrations symbols function-scoped, mirroring the existing local-import convention in this file):

```python
# Thumbnails are small; cap the fetch well under the artifact budget.
_SOURCE_PREVIEW_MAX_BYTES = 5 * 1024 * 1024
_SOURCE_PREVIEW_URL_TTL_SECONDS = 300


async def get_source_preview(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    artifact_id: UUID,
) -> "SourcePreviewResponse":
    """Return the draft live-mirror preview for a connector-bound artifact.

    Owner-only, pre-publish-only, google_drive-only. Fetches the current source
    modifiedTime + thumbnailLink server-side, computes the drift flag against the
    stored baseline, and serves the thumbnail from a modifiedTime-versioned S3
    cache key (fetching + caching on a miss). Never writes the artifact's sync
    fields — the preview moves no authoritative bytes.

    Raises:
        HTTPException(404): Framework/artifact not owned, or artifact is upload-kind.
        HTTPException(409): Framework not pre-publish, or connection needs re-auth.
        HTTPException(502): Provider failure.
    """
    from app.integrations import google_drive
    from app.integrations.google_drive import (
        DriveFileTooLargeError,
        GoogleDriveAuthError,
        GoogleDriveError,
    )
    from app.modules.frameworks.schemas import SourcePreviewResponse
    from app.modules.integrations.service import get_active_connection_with_fresh_token

    framework = await _load_owned_framework(db, contributor, framework_id)
    _require_editable_artifacts(framework)
    artifact = await db.scalar(
        select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.framework_id == framework.id,
        )
    )
    if artifact is None or artifact.source_kind != "google_drive" or artifact.source_connection_id is None or artifact.source_external_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No connector source for this artifact.")

    _, access_token = await get_active_connection_with_fresh_token(
        db, user_id=contributor.id, connection_id=artifact.source_connection_id
    )
    try:
        modified_time, thumbnail_link = await google_drive.fetch_drive_source_state(
            access_token=access_token, file_id=artifact.source_external_id
        )
    except GoogleDriveAuthError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "reauth_required", "message": "The connection is no longer authorized. Reconnect it."},
        ) from None
    except GoogleDriveError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The file provider is unavailable.") from exc

    source_updated = bool(modified_time) and modified_time != (artifact.source_synced_revision or "")

    settings = get_settings()
    bucket = settings.s3_artifacts_bucket
    preview_url: str | None = None
    if thumbnail_link and modified_time:
        prefix = f"frameworks/{framework.id}/artifacts/{artifact.id}/source-preview/"
        key = f"{prefix}{modified_time}.png"
        if not s3.storage.object_exists(bucket, key):
            try:
                body = await google_drive.download_drive_thumbnail(
                    thumbnail_link=thumbnail_link,
                    access_token=access_token,
                    max_bytes=_SOURCE_PREVIEW_MAX_BYTES,
                )
            except (GoogleDriveError, DriveFileTooLargeError):
                body = None
            if body is not None:
                # Clear any prior-revision cache object, then write the new one.
                s3.storage.delete_prefix(bucket, prefix)
                s3.storage.upload_bytes(bucket=bucket, key=key, body=body, mime_type="image/png")
        if s3.storage.object_exists(bucket, key):
            preview_url = s3.storage.presigned_get(bucket, key, _SOURCE_PREVIEW_URL_TTL_SECONDS)

    return SourcePreviewResponse(
        preview_url=preview_url,
        source_updated=source_updated,
        source_last_synced_at=artifact.source_last_synced_at,
    )
```

- [ ] **Step 11: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/modules/test_frameworks_source_preview.py -v`
Expected: PASS

- [ ] **Step 12: Add the router endpoint + integration test**

Create `backend/tests/integration/test_frameworks_source_preview.py` with three cases (reuse the fixtures used by the existing `test_integrations_files.py` for an authenticated contributor + a draft framework + a stubbed Drive):

```python
@pytest.mark.asyncio
async def test_source_preview_owner_draft_returns_flags(owner_draft_drive_artifact_client, ids) -> None:
    """Owner viewing a draft google_drive artifact gets preview_url + source_updated."""
    fw_id, art_id = ids
    resp = await owner_draft_drive_artifact_client.get(
        f"/v1/frameworks/{fw_id}/artifacts/{art_id}/source-preview"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"preview_url", "source_updated", "source_last_synced_at"}


@pytest.mark.asyncio
async def test_source_preview_non_owner_forbidden(other_contributor_client, ids) -> None:
    """A different contributor cannot read another's source preview -> 404 (not owned)."""
    fw_id, art_id = ids
    resp = await other_contributor_client.get(
        f"/v1/frameworks/{fw_id}/artifacts/{art_id}/source-preview"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_source_preview_published_conflict(owner_published_drive_artifact_client, published_ids) -> None:
    """A published framework is not pre-publish -> preview refused with 409."""
    fw_id, art_id = published_ids
    resp = await owner_published_drive_artifact_client.get(
        f"/v1/frameworks/{fw_id}/artifacts/{art_id}/source-preview"
    )
    assert resp.status_code == 409
```

In `backend/app/modules/frameworks/router.py`, add after the `from-connector` endpoint (and add `SourcePreviewResponse` to the schema imports at the top):

```python
@router.get(
    "/{framework_id}/artifacts/{artifact_id}/source-preview",
    response_model=SourcePreviewResponse,
    summary="Draft live-mirror preview for a connector-bound artifact",
    description=(
        "Owner-only, pre-publish-only. Returns a presigned thumbnail of the "
        "current source file and whether the source changed since import. Never "
        "exposed on public, catalog, or buyer surfaces."
    ),
)
async def get_artifact_source_preview(
    framework_id: UUID,
    artifact_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> SourcePreviewResponse:
    """Return the owner-only draft source preview for a connector-bound artifact."""
    return await service.get_source_preview(db, contributor, framework_id, artifact_id)
```

- [ ] **Step 13: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/integration/test_frameworks_source_preview.py tests/unit/modules/test_frameworks_source_preview.py tests/unit/test_google_drive_integration.py tests/unit/test_s3_storage.py -v`
Expected: PASS

- [ ] **Step 14: Lint + typecheck**

Run: `cd backend && uv run ruff check app/modules/frameworks app/integrations && uv run mypy app/modules/frameworks app/integrations`
Expected: clean.

- [ ] **Step 15: Commit**

```bash
git add backend/app/integrations/google_drive.py backend/app/integrations/s3.py backend/app/modules/frameworks/schemas.py backend/app/modules/frameworks/service.py backend/app/modules/frameworks/router.py backend/tests
git commit -m "Add owner-only draft source-preview endpoint with S3-cached Drive thumbnails"
```

---

### Task 3: Publish cleanup + confidentiality tests

**Files:**
- Modify: `backend/app/modules/frameworks/service.py` (`publish_framework`, ~1740)
- Test: `backend/tests/integration/test_frameworks_source_preview.py`, `backend/tests/unit/modules/test_frameworks_source_preview.py`

**Interfaces:**
- Consumes: `S3Storage.delete_prefix`, `publish_framework(db, contributor, framework_id) -> FrameworkResponse`, `ArtifactResponse` field set.
- Produces: publish deletes `frameworks/{fw}/artifacts/{art}/source-preview/` for each artifact; binding columns untouched.

- [ ] **Step 1: Write the failing test — publish clears preview cache**

Add to `backend/tests/integration/test_frameworks_source_preview.py`:

```python
@pytest.mark.asyncio
async def test_publish_deletes_source_preview_objects(monkeypatch, publishable_drive_framework) -> None:
    """Publishing deletes each artifact's source-preview/* cache; binding columns persist."""
    db, contributor, framework, artifact = publishable_drive_framework
    deleted_prefixes: list[str] = []
    from app.modules.frameworks import service
    monkeypatch.setattr(service.s3.storage, "delete_prefix", lambda bucket, prefix: deleted_prefixes.append(prefix))

    await service.publish_framework(db, contributor, framework.id)

    assert f"frameworks/{framework.id}/artifacts/{artifact.id}/source-preview/" in deleted_prefixes
    refreshed = await db.get(type(artifact), artifact.id)
    assert refreshed.source_kind == "google_drive"
    assert refreshed.source_external_id == artifact.source_external_id
```

`publishable_drive_framework` builds a framework in a status `publish_framework` accepts (follow the existing passing publish test's setup for the correct precondition status and any pipeline stubs), owning one `google_drive` artifact.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_frameworks_source_preview.py::test_publish_deletes_source_preview_objects -v`
Expected: FAIL — publish does not delete preview objects.

- [ ] **Step 3: Delete preview cache on publish**

In `publish_framework`, after the framework status is set to `"published"` and before/after the audit write (inside the same successful path, before `await db.commit()`), add:

```python
    # Connectors Phase B: the draft live-mirror preview is scaffolding for
    # authoring only. On publish, drop the cached source-preview thumbnails so
    # nothing draft-only lingers behind the sold, frozen version. Source binding
    # columns are kept — Phase C re-sync needs them.
    settings = get_settings()
    preview_artifacts = (
        (await db.execute(select(Artifact).where(Artifact.framework_id == framework.id)))
        .scalars()
        .all()
    )
    for art in preview_artifacts:
        if art.source_kind == "google_drive":
            s3.storage.delete_prefix(
                settings.s3_artifacts_bucket,
                f"frameworks/{framework.id}/artifacts/{art.id}/source-preview/",
            )
```

`get_settings`, `select`, `Artifact`, and `s3` are already imported in `service.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_frameworks_source_preview.py::test_publish_deletes_source_preview_objects -v`
Expected: PASS

- [ ] **Step 5: Write the confidentiality test — preview fields never on ArtifactResponse**

Add to `backend/tests/unit/modules/test_frameworks_source_preview.py`:

```python
def test_artifact_response_has_no_source_preview_fields() -> None:
    """The shared ArtifactResponse must never carry preview_url or drift fields.

    Structural guard: buyer/catalog/owner-list all serialize ArtifactResponse, so
    a preview field here would leak the draft-only mirror onto sold surfaces.
    """
    from app.modules.frameworks.schemas import ArtifactResponse

    forbidden = {"preview_url", "source_updated", "source_external_id", "source_connection_id", "source_synced_revision"}
    assert forbidden.isdisjoint(ArtifactResponse.model_fields.keys())
```

- [ ] **Step 6: Run test to verify it passes (guards existing design, must be green now)**

Run: `cd backend && uv run pytest tests/unit/modules/test_frameworks_source_preview.py::test_artifact_response_has_no_source_preview_fields -v`
Expected: PASS (no one added these fields to `ArtifactResponse` — this test locks that in).

- [ ] **Step 7: Lint + typecheck + full frameworks suite**

Run: `cd backend && uv run ruff check app/modules/frameworks && uv run mypy app/modules/frameworks && uv run pytest tests/integration/test_frameworks_source_preview.py tests/unit/modules/test_frameworks_source_preview.py -v`
Expected: clean + PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/modules/frameworks/service.py backend/tests
git commit -m "Delete source-preview cache on publish and lock preview fields out of ArtifactResponse"
```

---

### Task 4: GDPR revoke + purge, and Drive URL hardening

**Files:**
- Modify: `backend/app/modules/gdpr/anonymise.py` (`anonymise_user_records`)
- Modify: `backend/app/integrations/google_drive.py` (`quote` file_id/folder_id in remaining URL builders)
- Test: `backend/tests/unit/modules/` (GDPR anonymise test file — reuse existing), `backend/tests/unit/test_google_drive_integration.py`

**Interfaces:**
- Consumes: `revoke_drive_token(token) -> None` (non-raising), `decrypt_connector_token(str) -> str`, `OAuthConnection` model.
- Produces: after anonymise, zero `oauth_connections` rows for the user + best-effort Google revoke; `get_drive_file_metadata` / `download_drive_file` / `list_drive_files` percent-encode `file_id`/`folder_id`.

- [ ] **Step 1: Write the failing test — deletion purges connections**

Add to the existing GDPR anonymise unit test module (find it: `grep -rl "anonymise_user_records" backend/tests`). Test:

```python
@pytest.mark.asyncio
async def test_anonymise_revokes_and_deletes_oauth_connections(monkeypatch, gdpr_user_with_connection) -> None:
    """Account deletion best-effort revokes at Google and deletes oauth_connections rows."""
    db, user, request_id, connection = gdpr_user_with_connection
    revoked: list[str] = []
    from app.modules.gdpr import anonymise
    async def _revoke(token: str) -> None:
        revoked.append(token)
    monkeypatch.setattr(anonymise, "revoke_drive_token", _revoke)

    await anonymise.anonymise_user_records(
        db=db, user_id=user.id, request_id=request_id, completed_at=datetime.now(UTC),
    )

    from app.modules.integrations.models import OAuthConnection
    from sqlalchemy import select
    remaining = (await db.execute(select(OAuthConnection).where(OAuthConnection.user_id == user.id))).scalars().all()
    assert remaining == []
    assert len(revoked) >= 1
```

`gdpr_user_with_connection` builds a user with a scheduled deletion request and one active `OAuthConnection` (encrypted tokens via `encrypt_connector_token`). Follow the existing anonymise-test fixtures for the user + `AccountDeletionRequest` setup.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules -k anonymise_revokes_and_deletes -v`
Expected: FAIL — connections remain; `revoke_drive_token` not referenced by `anonymise`.

- [ ] **Step 3: Revoke + delete connections in anonymise**

In `backend/app/modules/gdpr/anonymise.py`, add imports at top:

```python
from app.core.security import decrypt_connector_token
from app.integrations.google_drive import revoke_drive_token
from app.modules.integrations.models import OAuthConnection
```

Inside `anonymise_user_records`, after the existing `delete(OAuthAccount)…` / `delete(KycDocument)…` block, add:

```python
    # Connectors: revoke each grant at Google (best-effort, non-raising) then
    # delete the rows. The user record is anonymised, not deleted, so the FK
    # CASCADE never fires — purge explicitly, or encrypted Drive tokens and a
    # live Google grant would outlive the account.
    connections = list(
        (
            await db.execute(
                select(OAuthConnection).where(OAuthConnection.user_id == user_id)
            )
        ).scalars()
    )
    for connection in connections:
        for encrypted in (connection.access_token_encrypted, connection.refresh_token_encrypted):
            if encrypted:
                await revoke_drive_token(decrypt_connector_token(encrypted))
    await db.execute(delete(OAuthConnection).where(OAuthConnection.user_id == user_id))
```

`select` and `delete` are already imported in this module.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/modules -k anonymise_revokes_and_deletes -v`
Expected: PASS

- [ ] **Step 5: Write the failing test — file_id percent-encoded**

Add to `backend/tests/unit/test_google_drive_integration.py`:

```python
@pytest.mark.asyncio
async def test_get_drive_file_metadata_encodes_file_id(monkeypatch) -> None:
    """A file_id with URL-significant chars is percent-encoded, never injected into the path/query."""
    captured: dict[str, str] = {}

    class _Resp:
        status_code = 200
        def json(self) -> dict[str, object]:
            return {"id": "x", "name": "n", "mimeType": "application/pdf", "size": "1", "modifiedTime": "t"}

    class _Client:
        def __init__(self, *a, **k) -> None: ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a) -> None: ...
        async def get(self, url, params, headers) -> _Resp:
            captured["url"] = url
            return _Resp()

    monkeypatch.setattr("app.integrations.google_drive.httpx.AsyncClient", _Client)
    from app.integrations.google_drive import get_drive_file_metadata
    await get_drive_file_metadata(access_token="t", file_id="a b?c/d")
    assert "?c" not in captured["url"].split("/files/")[1]
    assert "a%20b" in captured["url"]
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_google_drive_integration.py::test_get_drive_file_metadata_encodes_file_id -v`
Expected: FAIL — raw `file_id` interpolated into the URL.

- [ ] **Step 7: Percent-encode file_id/folder_id in Drive URL builders**

In `backend/app/integrations/google_drive.py`, add `from urllib.parse import quote` at module top (if not already present from Task 2's function-local import — hoist it to module scope). Then:

- In `get_drive_file_metadata`: `f"{DRIVE_API_BASE}/files/{quote(file_id, safe='')}"`.
- In `download_drive_file` (both the export and media branches): `quote(file_id, safe='')` in the URL path.
- In `list_drive_files`: the `folder_id` goes into the Drive `q` string via `_escape_drive_query` (already correct for q-syntax) — leave it; the `q`-string escaping is the right defense there, not URL-encoding. Only path-interpolated ids get `quote`.

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_google_drive_integration.py tests/integration/test_integrations_files.py -v`
Expected: PASS (existing Drive tests still green with encoding applied).

- [ ] **Step 9: Lint + typecheck**

Run: `cd backend && uv run ruff check app/modules/gdpr app/integrations && uv run mypy app/modules/gdpr app/integrations`
Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add backend/app/modules/gdpr/anonymise.py backend/app/integrations/google_drive.py backend/tests
git commit -m "Revoke and purge connector grants on account deletion; percent-encode Drive file ids"
```

---

### Task 5: OpenAPI + frontend draft preview badge

**Files:**
- Modify: `contracts/openapi.yaml` (regenerated), `frontend/src/lib/generated/{sdk.gen.ts,types.gen.ts}` (regenerated)
- Create: `frontend/src/components/modules/frameworks/source-preview-badge.tsx`
- Modify: `frontend/src/components/modules/frameworks/artifact-manifest.tsx` (mount the badge)
- Create: `frontend/tests/unit/components/frameworks/source-preview-badge.test.tsx`

**Interfaces:**
- Consumes generated `getArtifactSourcePreviewV1FrameworksFrameworkIdArtifactsArtifactIdSourcePreviewGet` (name will match the codegen convention seen for other framework artifact endpoints); `SourcePreviewResponse { preview_url: string | null; source_updated: boolean; source_last_synced_at: string | null }`; `ArtifactResponse` (now includes `source_kind`).
- Produces: `SourcePreviewBadge` component rendering a thumbnail + "Source updated" badge for owner draft google_drive artifacts.

- [ ] **Step 1: Regenerate the API contract + client**

The backend endpoint and schema are already in FastAPI; export the OpenAPI and regenerate. Run:

```bash
cd backend && uv run python -c "import json, app.main as m; open('../contracts/openapi.yaml','w').close()" 2>/dev/null || true
```

Then regenerate via the project's contract export command (the same one used in Phase A — check `backend/` scripts or `Makefile`/`package.json` for the openapi export target; it writes `contracts/openapi.yaml` from `app.main.app.openapi()`). After `contracts/openapi.yaml` is updated:

```bash
cd frontend && npm run generate:api
```

Verify `getArtifactSourcePreview…` and `SourcePreviewResponse` now exist:

```bash
cd frontend && grep -R "SourcePreview" src/lib/generated/ | head
```

Expected: the type and sdk fn are present. Note the exact generated fn name for Step 4.

- [ ] **Step 2: Write the failing component test**

Create `frontend/tests/unit/components/frameworks/source-preview-badge.test.tsx`:

```tsx
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@/lib/generated/sdk.gen", () => ({
  getArtifactSourcePreviewV1FrameworksFrameworkIdArtifactsArtifactIdSourcePreviewGet: vi.fn(),
}));
vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({}),
  describeGeneratedError: () => "err",
  configureBrowserClient: () => {},
}));

import { getArtifactSourcePreviewV1FrameworksFrameworkIdArtifactsArtifactIdSourcePreviewGet as getPreview } from "@/lib/generated/sdk.gen";
import { SourcePreviewBadge } from "@/components/modules/frameworks/source-preview-badge";

describe("SourcePreviewBadge", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the thumbnail and 'Source updated' badge when the source drifted", async () => {
    (getPreview as unknown as vi.Mock).mockResolvedValue({
      data: { preview_url: "https://s3/thumb.png", source_updated: true, source_last_synced_at: "2026-07-01T00:00:00Z" },
      error: undefined,
    });
    render(<SourcePreviewBadge frameworkId="fw1" artifactId="a1" />);
    expect(await screen.findByText(/source updated/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("img")).toHaveAttribute("src", "https://s3/thumb.png"));
  });

  it("shows no badge when the source is unchanged", async () => {
    (getPreview as unknown as vi.Mock).mockResolvedValue({
      data: { preview_url: "https://s3/thumb.png", source_updated: false, source_last_synced_at: null },
      error: undefined,
    });
    render(<SourcePreviewBadge frameworkId="fw1" artifactId="a1" />);
    await screen.findByRole("img");
    expect(screen.queryByText(/source updated/i)).toBeNull();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/components/frameworks/source-preview-badge.test.tsx`
Expected: FAIL — component does not exist.

- [ ] **Step 4: Implement the badge component**

Create `frontend/src/components/modules/frameworks/source-preview-badge.tsx`. Use the exact generated fn name confirmed in Step 1 (shown here as `getArtifactSourcePreview…`):

```tsx
"use client";

/**
 * Draft-only live-mirror preview for a connector-bound artifact.
 *
 * Owner-only surface (contributor dashboard, draft framework). Fetches the
 * current Drive thumbnail + drift flag from the owner-only backend endpoint and
 * shows a "Source updated" badge when the external source changed since import.
 * Never rendered on public/catalog/buyer surfaces.
 */
import { useEffect, useState } from "react";

import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { getArtifactSourcePreviewV1FrameworksFrameworkIdArtifactsArtifactIdSourcePreviewGet as getSourcePreview } from "@/lib/generated/sdk.gen";

type Props = { frameworkId: string; artifactId: string };

export function SourcePreviewBadge({ frameworkId, artifactId }: Props) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [updated, setUpdated] = useState(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      const res = await getSourcePreview({
        path: { framework_id: frameworkId, artifact_id: artifactId },
        headers: getAccessTokenHeaders(),
      });
      if (!mounted || res.error || !res.data) return;
      setPreviewUrl(res.data.preview_url);
      setUpdated(res.data.source_updated);
    })();
    return () => { mounted = false; };
  }, [frameworkId, artifactId]);

  if (!previewUrl) return null;

  return (
    <div className="mt-3 flex items-center gap-3">
      <img
        src={previewUrl}
        alt="Live source preview"
        className="h-16 w-16 rounded-md border border-border-default object-cover"
      />
      {updated && (
        <span className="inline-flex items-center rounded-full bg-warning/10 px-3 py-1.5 text-xs font-semibold text-warning">
          Source updated
        </span>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/components/frameworks/source-preview-badge.test.tsx`
Expected: PASS

- [ ] **Step 6: Mount the badge in the artifact manifest (owner draft, google_drive only)**

In `frontend/src/components/modules/frameworks/artifact-manifest.tsx`, import the badge and render it inside each artifact row, gated to draft status + `source_kind === "google_drive"`:

```tsx
import { SourcePreviewBadge } from "@/components/modules/frameworks/source-preview-badge";
```

Inside the per-artifact render (where each `artifact` row is drawn), after the existing artifact detail block, add:

```tsx
{frameworkStatus === "draft" && (artifact as { source_kind?: string }).source_kind === "google_drive" && (
  <SourcePreviewBadge frameworkId={frameworkId} artifactId={artifact.id} />
)}
```

(`frameworkStatus` and `frameworkId` are already props of `ArtifactManifest`.)

- [ ] **Step 7: Typecheck + lint + test at 375px sanity**

Run: `cd frontend && npm run typecheck && npm run lint && npx vitest run tests/unit/components/frameworks/source-preview-badge.test.tsx`
Expected: clean + PASS. Manually confirm the badge/thumbnail layout holds at 375px (thumbnail 64px + wrapping badge; `flex items-center gap-3` wraps acceptably).

- [ ] **Step 8: Commit**

```bash
git add contracts/openapi.yaml frontend/src/lib/generated frontend/src/components/modules/frameworks/source-preview-badge.tsx frontend/src/components/modules/frameworks/artifact-manifest.tsx frontend/tests/unit/components/frameworks/source-preview-badge.test.tsx
git commit -m "Add draft source-preview thumbnail and 'Source updated' badge to the artifact manifest"
```

---

## Verification (whole plan)

- `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head` — all succeed.
- `cd backend && uv run pytest tests/unit/test_google_drive_integration.py tests/unit/test_s3_storage.py tests/unit/modules/test_frameworks_source_preview.py tests/integration/test_frameworks_source_preview.py tests/integration/test_integrations_files.py -v` — all pass.
- `cd backend && uv run ruff check . && uv run mypy app` — clean.
- `cd frontend && npm run typecheck && npm run lint && npx vitest run` — clean + green.
- Manual: import a Drive file → edit it in Drive → reload the draft framework → thumbnail refreshes and "Source updated" badge appears; publish → preview objects gone, badge absent; delete account → `oauth_connections` rows purged, Google revoke attempted.
- Confirm `preview_url`/drift never appear on catalog, buyer library, or the owner artifact list (`ArtifactResponse`).

## Risks (flagged)

- **Contract export command** — Step 5.1 assumes the Phase-A openapi export target. If the repo uses a specific script, use it verbatim; do not hand-edit `contracts/openapi.yaml`.
- **Drive thumbnail lag** — Google regenerates thumbnails asynchronously; the image may trail an edit by seconds while the badge (driven by `modifiedTime`) is immediately accurate. Expected, documented in the spec.
- **Scope creep toward re-sync / live-mirror-of-sold** — both are out of scope (Phase C / permanently). Reject in review.
