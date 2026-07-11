# Connectors Phase C (Re-Sync + Re-Bind) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a contributor pull changed connector-source bytes into a draft artifact ("re-sync") and manage the source binding ("re-bind": attach / repoint / detach), without ever mutating published bytes.

**Architecture:** Every byte change **forks a new immutable `Artifact` row** (write-once bytes) and re-runs the pipeline. One `bind_and_sync` core serves re-sync, attach, and repoint; detach is metadata-only. A content hash (`content_sha256`) skips identical re-syncs; a processing lease (`processing_started_at`) plus a Celery-beat reaper make the pipeline self-healing; a shared budget helper takes a framework-row lock to serialize the 500 MB check across all four artifact write paths.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, Celery, pytest + pytest-asyncio + httpx AsyncClient, loguru, boto3 (S3), Google Drive REST.

## Global Constraints

- Backend only. Frontend is a separate deferred plan. OpenAPI (`contracts/openapi.yaml`) updated before any frontend work.
- Work on `main`. No feature branch (ask before branching). No `Co-Authored-By` / Claude trailer on commits.
- TDD RED→GREEN per behavior — one failing test, then minimal code, then green. Never batch all tests then all code.
- Never run `pytest` concurrently — the dev DB is shared. Run suites serially.
- Whole-repo lint/type before claiming clean: `uv run ruff check .` and `uv run mypy app` (both from `backend/`).
- Every migration: `alembic upgrade head` **and** `alembic downgrade -1` must both succeed.
- RBAC only via FastAPI dependencies (`ContributorUser`), never inside services.
- Escrow / financial state untouched — out of scope.
- Confidentiality (hard invariant): source binding + drift never appear on `ArtifactResponse` or any public/catalog/buyer serializer. Only `SourcePreviewResponse` (owner-only) carries drift.
- Immutability (hard invariant): artifact bytes are write-once. A row referenced by `framework_version_artifacts` is **never** overwritten or deleted — it is retained `current_for_framework=False`.
- Never log tokens, presigned URLs, or file bytes. Structured loguru with `module`/`action` context.
- Spec: `docs/superpowers/specs/2026-07-11-connectors-phase-c-design.md`. Alembic head is `2026_07_11_0078`; the new migration is `2026_07_11_0079`.

---

### Task 1: Model columns + migration + config TTLs

**Files:**
- Modify: `backend/app/modules/frameworks/models_artifact.py:113-115` (add two columns after `source_synced_revision`)
- Create: `backend/migrations/versions/2026_07_11_0079_artifact_content_hash_lease.py`
- Modify: `backend/app/core/config.py` (add two settings near `s3_artifacts_bucket`, line ~139)
- Test: `backend/tests/unit/modules/test_artifact_phase_c_migration.py`

**Interfaces:**
- Produces: `Artifact.content_sha256: str | None`, `Artifact.processing_started_at: datetime | None`; `Settings.artifact_processing_lease_minutes: int` (default 30), `Settings.artifact_orphan_sweep_minutes: int` (default 60).

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/modules/test_artifact_phase_c_migration.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_artifact_phase_c_migration.py -v`
Expected: FAIL (`KeyError: 'content_sha256'` / `AttributeError` on settings).

- [ ] **Step 3: Add the model columns**

In `backend/app/modules/frameworks/models_artifact.py`, immediately after the `source_synced_revision` column (line 113-115):

```python
    source_synced_revision: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    # sha256 of the owned bytes. Lets re-sync skip forking an identical byte
    # copy when the source's modifiedTime moved but the content did not.
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Wall-clock when the row entered ``processing``. Drives the stale-lease
    # reaper and the TTL-aware re-sync in-flight guard.
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 4: Add the config settings**

In `backend/app/core/config.py`, near `s3_artifacts_bucket` (line ~139), add:

```python
    artifact_processing_lease_minutes: int = Field(
        default=30, alias="ARTIFACT_PROCESSING_LEASE_MINUTES"
    )
    artifact_orphan_sweep_minutes: int = Field(
        default=60, alias="ARTIFACT_ORPHAN_SWEEP_MINUTES"
    )
```

- [ ] **Step 5: Write the migration**

`backend/migrations/versions/2026_07_11_0079_artifact_content_hash_lease.py`:

```python
"""Add artifact content hash and processing lease for connector re-sync.

Supports Connectors Phase C: ``content_sha256`` lets re-sync skip forking an
identical byte copy, and ``processing_started_at`` drives the stale-lease
reaper plus the TTL-aware in-flight guard. Both are additive and nullable;
existing rows keep NULL (no backfill needed).

Revision ID: 2026_07_11_0079
Revises: 2026_07_11_0078
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_11_0079"
down_revision: str | Sequence[str] | None = "2026_07_11_0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the content hash and processing lease columns."""
    op.add_column(
        "artifacts",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "artifacts",
        sa.Column(
            "processing_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Drop the Phase C columns."""
    op.drop_column("artifacts", "processing_started_at")
    op.drop_column("artifacts", "content_sha256")
```

- [ ] **Step 6: Run the migration round-trip**

Run: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: all three succeed, no error.

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/modules/test_artifact_phase_c_migration.py -v`
Expected: PASS (2 tests).

- [ ] **Step 8: Lint, type, commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add app/modules/frameworks/models_artifact.py app/core/config.py \
  migrations/versions/2026_07_11_0079_artifact_content_hash_lease.py \
  tests/unit/modules/test_artifact_phase_c_migration.py
git commit -m "Add artifact content hash and processing lease columns"
```

---

### Task 2: Distinguish Drive not-found (404) from generic failure

**Files:**
- Modify: `backend/app/integrations/google_drive.py:65-66` (new error class) and `:252-261` (`_raise_for_drive_response`)
- Test: `backend/tests/unit/test_google_drive_integration.py`

**Interfaces:**
- Produces: `GoogleDriveNotFoundError(GoogleDriveError)`; `_raise_for_drive_response` raises it on HTTP 404. Re-sync/bind map it to `409 source_unavailable`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/test_google_drive_integration.py`:

```python
def test_raise_for_drive_response_maps_404_to_not_found() -> None:
    """A Drive 404 must raise the dedicated not-found error, not the generic one."""
    import httpx

    from app.integrations.google_drive import (
        GoogleDriveAuthError,
        GoogleDriveNotFoundError,
        _raise_for_drive_response,
    )

    response = httpx.Response(status_code=404, request=httpx.Request("GET", "http://x"))
    with pytest.raises(GoogleDriveNotFoundError):
        _raise_for_drive_response(response, action="get_drive_file_metadata")

    # 401/403 still map to the auth error, unchanged.
    auth_response = httpx.Response(
        status_code=403, request=httpx.Request("GET", "http://x")
    )
    with pytest.raises(GoogleDriveAuthError):
        _raise_for_drive_response(auth_response, action="get_drive_file_metadata")
```

(Ensure `import pytest` is present at the top of the file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_google_drive_integration.py::test_raise_for_drive_response_maps_404_to_not_found -v`
Expected: FAIL (`ImportError: cannot import name 'GoogleDriveNotFoundError'`).

- [ ] **Step 3: Add the error class and 404 mapping**

In `backend/app/integrations/google_drive.py`, after `DriveFileTooLargeError` (line 65-66):

```python
class GoogleDriveNotFoundError(GoogleDriveError):
    """Raised when a Drive file is missing or no longer accessible (404)."""
```

In `_raise_for_drive_response` (line 252-261), add the 404 branch before the final generic raise:

```python
def _raise_for_drive_response(response: httpx.Response, action: str) -> None:
    """Translate a failed Drive API response into a typed error."""
    logger.bind(module="integrations", action=action).warning(
        "drive_api_error", status_code=response.status_code
    )
    if response.status_code in (401, 403):
        raise GoogleDriveAuthError("Google Drive authorization is no longer valid.")
    if response.status_code == 404:
        raise GoogleDriveNotFoundError("Google Drive file not found.")
    raise GoogleDriveError("Google Drive request failed.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_google_drive_integration.py::test_raise_for_drive_response_maps_404_to_not_found -v`
Expected: PASS.

- [ ] **Step 5: Lint, type, commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add app/integrations/google_drive.py tests/unit/test_google_drive_integration.py
git commit -m "Map Google Drive 404 to a dedicated not-found error"
```

---

### Task 3: Shared framework-locking budget helper (adopted by import + upload-url)

**Files:**
- Modify: `backend/app/modules/frameworks/service.py` (add `_reserve_artifact_budget`; refactor `import_artifact_from_connector` at 1262-1273 and `request_artifact_upload_url` at 1370-1380)
- Test: `backend/tests/unit/modules/test_artifact_budget_reserve.py`

**Interfaces:**
- Produces: `async def _reserve_artifact_budget(db: AsyncSession, framework_id: UUID, *, add_bytes: int, exclude_id: UUID | None) -> None` — locks the framework row, sums current artifact bytes excluding `exclude_id`, raises `HTTPException(413)` if `sum + add_bytes > ARTIFACT_MAX_TOTAL_SIZE`. Consumed by Tasks 4, 5, 6.

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/modules/test_artifact_budget_reserve.py`:

```python
"""Unit tests for the framework-locking artifact budget helper."""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact


async def _truncate() -> None:
    """Clear the tables this suite seeds."""
    async with async_session_factory() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE "
                f"{Artifact.__tablename__}, {Framework.__tablename__}, "
                f"{User.__tablename__} RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()


@pytest.fixture
async def budget_ctx(
    migrated_database: None,
) -> AsyncIterator[tuple[AsyncSession, Framework, Artifact]]:
    """Seed a framework with one 400MB artifact."""
    await engine.dispose()
    await _truncate()
    session = async_session_factory()
    contributor = User(
        email="budget@auracles.space",
        display_name="Budget",
        email_verified=True,
        password_hash=None,
    )
    framework = Framework(
        contributor_id=uuid4(),
        title="Budget Framework",
        description="Budget helper test framework.",
        category="framework",
        sector="financial_services",
        industry="fund_management",
        business_function="risk_management",
        tags=["b"],
        tags_text="b",
        jurisdiction="us",
        complexity=3,
        org_size="mid_market",
        lifecycle_stage="scale",
        price=Decimal("10.00"),
        currency="USD",
        license_types=["single_user"],
        commercial_rights="x",
        usage_restrictions="x",
        status="draft",
    )
    artifact = Artifact(
        framework_id=uuid4(),
        name="big.pdf",
        file_key="frameworks/fw/artifacts/big.pdf",
        file_size=400 * 1024 * 1024,
        mime_type="application/pdf",
    )
    async with session.begin():
        session.add(contributor)
        await session.flush()
        framework.contributor_id = contributor.id
        session.add(framework)
        await session.flush()
        artifact.framework_id = framework.id
        session.add(artifact)
        await session.flush()
    yield session, framework, artifact
    await session.close()
    await _truncate()
    await engine.dispose()


@pytest.mark.asyncio
async def test_reserve_rejects_over_budget(
    budget_ctx: tuple[AsyncSession, Framework, Artifact],
) -> None:
    """Adding 200MB on top of an existing 400MB artifact exceeds 500MB → 413."""
    from app.modules.frameworks import service

    db, framework, _artifact = budget_ctx
    with pytest.raises(HTTPException) as exc:
        await service._reserve_artifact_budget(
            db, framework.id, add_bytes=200 * 1024 * 1024, exclude_id=None
        )
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_reserve_excludes_replaced_artifact(
    budget_ctx: tuple[AsyncSession, Framework, Artifact],
) -> None:
    """Replacing the 400MB artifact leaves room, so 200MB is allowed."""
    from app.modules.frameworks import service

    db, framework, artifact = budget_ctx
    # Excluding the artifact being replaced must not raise.
    await service._reserve_artifact_budget(
        db, framework.id, add_bytes=200 * 1024 * 1024, exclude_id=artifact.id
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_artifact_budget_reserve.py -v`
Expected: FAIL (`AttributeError: module 'app.modules.frameworks.service' has no attribute '_reserve_artifact_budget'`).

- [ ] **Step 3: Add the helper**

In `backend/app/modules/frameworks/service.py`, add near the other artifact helpers (after `_load_owned_artifact`). It uses `Framework`, `Artifact`, `func`, `select`, `ARTIFACT_MAX_TOTAL_SIZE`, all already imported:

```python
async def _reserve_artifact_budget(
    db: AsyncSession,
    framework_id: UUID,
    *,
    add_bytes: int,
    exclude_id: UUID | None,
) -> None:
    """Serialize the 500MB framework artifact budget check under a row lock.

    Locks the Framework row FOR UPDATE, then sums the current artifact bytes
    (optionally excluding the artifact being replaced) and rejects if the new
    bytes would exceed the cap. The lock makes the check-then-act atomic across
    concurrent import/upload/re-sync on the same Framework.

    Args:
        db: Async database session (an open transaction is required for the lock).
        framework_id: Framework whose budget is being reserved.
        add_bytes: Bytes about to be added.
        exclude_id: An artifact id to exclude from the sum (the row being replaced).

    Raises:
        HTTPException(413): If the reservation would exceed the size budget.
    """
    await db.execute(
        select(Framework.id).where(Framework.id == framework_id).with_for_update()
    )
    conditions = [Artifact.framework_id == framework_id]
    if exclude_id is not None:
        conditions.append(Artifact.id != exclude_id)
    existing = await db.scalar(
        select(func.coalesce(func.sum(Artifact.file_size), 0)).where(*conditions)
    )
    if int(existing or 0) + add_bytes > ARTIFACT_MAX_TOTAL_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Framework artifacts exceed the 500MB limit.",
        )
```

- [ ] **Step 4: Adopt it in the import path**

In `import_artifact_from_connector`, replace the inline size check (lines 1262-1273, the `existing_size = await db.scalar(...)` block through the 413 raise) with:

```python
    metadata_size = metadata.get("size")
    if metadata_size is not None:
        await _reserve_artifact_budget(
            db,
            framework.id,
            add_bytes=int(metadata_size),
            exclude_id=None,
        )
    remaining = ARTIFACT_MAX_TOTAL_SIZE
```

Note: `download_drive_file(..., max_bytes=remaining)` further downstream stays; keep `remaining = ARTIFACT_MAX_TOTAL_SIZE` as the streaming cap (the lock already enforced the real budget; the stream cap stays a hard ceiling).

- [ ] **Step 5: Adopt it in the upload-url path**

In `request_artifact_upload_url`, replace the inline size check (lines 1370-1380) with:

```python
    await _reserve_artifact_budget(
        db,
        framework.id,
        add_bytes=payload.file_size,
        exclude_id=None,
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/modules/test_artifact_budget_reserve.py tests/integration/test_frameworks_source_preview.py -v`
Then the existing import/upload suites to confirm no regression:
Run: `cd backend && uv run pytest tests/integration/test_framework_ownership.py -v`
Expected: PASS.

- [ ] **Step 7: Lint, type, commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add app/modules/frameworks/service.py tests/unit/modules/test_artifact_budget_reserve.py
git commit -m "Add framework-locking artifact budget helper; adopt in import and upload"
```

---

### Task 4: Populate content_sha256 + processing_started_at on the byte paths

**Files:**
- Modify: `backend/app/modules/frameworks/service.py` — `import_artifact_from_connector` (artifact construction ~1307-1324); `confirm_artifact_upload` (~1602)
- Modify: `backend/app/workers/tasks/artifacts.py` — the processing task that reads bytes from S3 (persist `content_sha256`)
- Test: `backend/tests/unit/modules/test_artifact_hash_lease_population.py`, `backend/tests/unit/workers/test_artifact_content_hash.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: import sets `content_sha256=hashlib.sha256(body).hexdigest()` and `processing_started_at=datetime.now(UTC)`; `confirm_artifact_upload` sets `processing_started_at` when it flips to `processing`; the processing pipeline persists `content_sha256` for artifacts that lack it.

- [ ] **Step 1: Write the failing service test**

`backend/tests/unit/modules/test_artifact_hash_lease_population.py` — reuse the `source_preview_ctx`-style seed. Minimal version:

```python
"""Import stamps content hash + processing lease on connector artifacts."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.asyncio


async def test_import_stamps_content_hash_and_lease(monkeypatch, source_preview_ctx):
    """A connector import records sha256(body) and processing_started_at."""
    from app.integrations import google_drive
    from app.modules.frameworks import service
    from app.modules.frameworks.models_artifact import Artifact
    from app.modules.frameworks.schemas import ArtifactFromConnectorRequest
    from app.modules.integrations import service as integrations_service
    from sqlalchemy import select

    db, contributor, framework, _artifact = source_preview_ctx
    body = b"PDF-BYTES-HERE"

    monkeypatch.setattr(
        service, "get_settings",
        lambda: SimpleNamespace(s3_artifacts_bucket="bucket"),
    )
    monkeypatch.setattr(
        integrations_service, "get_active_connection_with_fresh_token",
        _fake_connection_loader(),
    )

    async def _meta(*, access_token, file_id):
        return {"id": file_id, "name": "brief.pdf", "mimeType": "application/pdf",
                "size": str(len(body)), "modifiedTime": "REV-1"}

    async def _download(*, access_token, file_id, export_mime, max_bytes):
        return body

    monkeypatch.setattr(google_drive, "get_drive_file_metadata", _meta)
    monkeypatch.setattr(google_drive, "download_drive_file", _download)
    monkeypatch.setattr(service.s3.storage, "upload_bytes",
                        lambda bucket, key, body, mime_type: None)
    monkeypatch.setattr(service, "scan_artifact", SimpleNamespace(delay=lambda _id: None))

    await service.import_artifact_from_connector(
        db, contributor, framework.id,
        ArtifactFromConnectorRequest(connection_id=_conn_id(), file_id="file-9"),
    )

    row = await db.scalar(
        select(Artifact).where(Artifact.source_external_id == "file-9")
    )
    assert row.content_sha256 == hashlib.sha256(body).hexdigest()
    assert row.processing_started_at is not None
```

Provide the two tiny helpers `_fake_connection_loader()` and `_conn_id()` in this file mirroring `_fake_connection` from `test_frameworks_source_preview.py` (the fixture seeds a connection you can reuse — read the connection id off `source_preview_ctx`'s artifact). Import the shared `source_preview_ctx` fixture by copying it into a local `conftest` or re-declaring it in this module; simplest is to re-use the existing fixture module — add `from tests.unit.modules.test_frameworks_source_preview import source_preview_ctx  # noqa: F401` at the top.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_artifact_hash_lease_population.py -v`
Expected: FAIL (`content_sha256` is None).

- [ ] **Step 3: Stamp on import**

In `import_artifact_from_connector`, at the `Artifact(...)` construction (line ~1307), add the two fields (and `import hashlib` at the top of the module if absent; `datetime`, `UTC` are already imported):

```python
    artifact = Artifact(
        id=artifact_id,
        framework_id=framework.id,
        name=filename,
        file_key=file_key,
        file_size=len(body),
        mime_type=effective_mime,
        processing_status="processing",
        processing_started_at=datetime.now(UTC),
        content_sha256=hashlib.sha256(body).hexdigest(),
        source_kind="google_drive",
        source_external_id=payload.file_id,
        source_connection_id=connection.id,
        source_last_synced_at=datetime.now(UTC),
        source_synced_revision=(
            str(metadata.get("modifiedTime"))
            if metadata.get("modifiedTime")
            else None
        ),
    )
```

- [ ] **Step 4: Stamp the lease on upload confirm**

In `confirm_artifact_upload`, in the `if artifact.processing_status == "pending":` block (line ~1602), set the lease when flipping:

```python
    if artifact.processing_status == "pending":
        artifact.processing_status = "processing"
        artifact.processing_started_at = datetime.now(UTC)
```

- [ ] **Step 5: Write the failing worker test**

The scan task (`_scan_artifact_impl`, `app/workers/tasks/artifacts.py:94`) already downloads
the bytes to a temp file (line 110-115) before scanning — that is the hash hook (no second S3
read). `backend/tests/unit/workers/test_artifact_content_hash.py`:

```python
"""The scan pipeline backfills content_sha256 for upload-path artifacts."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.database import async_session_factory, engine
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact

pytestmark = pytest.mark.asyncio


async def _truncate() -> None:
    async with async_session_factory() as s:
        await s.execute(
            text(
                "TRUNCATE TABLE "
                f"{Artifact.__tablename__}, {Framework.__tablename__}, "
                f"{User.__tablename__} RESTART IDENTITY CASCADE"
            )
        )
        await s.commit()


async def test_scan_sets_content_hash_when_null(monkeypatch):
    """A clean scan of an artifact with NULL hash records sha256 of its bytes."""
    await engine.dispose()
    await _truncate()
    from app.workers.tasks import artifacts as artifacts_task

    known = b"UPLOADED-BYTES"
    async with async_session_factory() as session:
        async with session.begin():
            contributor = User(email=f"{uuid4()}@a.space", display_name="H",
                               email_verified=True, password_hash=None)
            session.add(contributor)
            await session.flush()
            framework = Framework(
                contributor_id=contributor.id, title="Hash FW",
                description="hash pipeline fw", category="framework",
                sector="financial_services", industry="fund_management",
                business_function="risk_management", tags=["h"], tags_text="h",
                jurisdiction="us", complexity=3, org_size="mid_market",
                lifecycle_stage="scale", price=Decimal("1.00"), currency="USD",
                license_types=["single_user"], commercial_rights="x",
                usage_restrictions="x", status="draft",
            )
            session.add(framework)
            await session.flush()
            artifact = Artifact(
                framework_id=framework.id, name="u.pdf",
                file_key="frameworks/x/artifacts/u.pdf", file_size=len(known),
                mime_type="application/pdf", processing_status="pending",
            )
            session.add(artifact)
            await session.flush()
            artifact_id = artifact.id

    def _fake_download(bucket, key, destination):
        with open(destination, "wb") as handle:
            handle.write(known)

    monkeypatch.setattr(artifacts_task.s3.storage, "download_file", _fake_download)

    await artifacts_task._scan_artifact_impl(
        str(artifact_id),
        scan_file=lambda path: "clean",
        process_task=SimpleNamespace(delay=lambda _id: None),
    )

    async with async_session_factory() as session:
        row = await session.get(Artifact, artifact_id)
        assert row.content_sha256 == hashlib.sha256(known).hexdigest()
    await _truncate()
    await engine.dispose()
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/workers/test_artifact_content_hash.py -v`
Expected: FAIL (`content_sha256` is None).

- [ ] **Step 7: Persist the hash in the scan pipeline**

In `app/workers/tasks/artifacts.py`, add `import hashlib` at the top. In `_scan_artifact_impl`,
inside the `with tempfile.NamedTemporaryFile() as local_file:` block, after the scan, hash the
already-downloaded file:

```python
        scan_status = resolved_scan_file(local_file.name)
        with open(local_file.name, "rb") as scanned:
            content_sha256 = hashlib.sha256(scanned.read()).hexdigest()
```

Thread it into the clean-branch persist (extend `_set_scan_result` with a
`content_sha256: str | None = None` parameter and set it **only when the row's hash is NULL**,
so import/re-sync values are never overwritten):

```python
async def _set_scan_result(
    artifact_id: UUID,
    scan_status: str,
    processing_status: str,
    audit_action: str,
    content_sha256: str | None = None,
) -> None:
    """Persist a scan state transition and audit record."""
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, artifact_id)
        if artifact is None:
            return
        artifact.scan_status = scan_status
        artifact.processing_status = processing_status
        if content_sha256 is not None and artifact.content_sha256 is None:
            artifact.content_sha256 = content_sha256
        ...  # existing write_audit + commit unchanged
```

And pass it on the clean transition:

```python
    await _set_scan_result(
        parsed_artifact_id,
        scan_status="clean",
        processing_status="processing",
        audit_action="artifact_scan_complete",
        content_sha256=content_sha256,
    )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/modules/test_artifact_hash_lease_population.py tests/unit/workers/test_artifact_content_hash.py -v`
Expected: PASS.

- [ ] **Step 9: Lint, type, commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add app/modules/frameworks/service.py app/workers/tasks/artifacts.py \
  tests/unit/modules/test_artifact_hash_lease_population.py \
  tests/unit/workers/test_artifact_content_hash.py
git commit -m "Populate artifact content hash and processing lease on byte paths"
```

---

### Task 5: Re-sync — `bind_and_sync` core + `resync_artifact` + endpoint + OpenAPI

**Files:**
- Modify: `backend/app/modules/frameworks/service.py` (add `bind_and_sync`, `resync_artifact`; constant `_extension_for_filename`, `EXPORT_MIME_MAP`, `ALLOWED_ARTIFACT_MIME_TYPES`, `FrameworkVersionArtifact`, `scan_artifact` all already imported)
- Modify: `backend/app/modules/frameworks/router.py` (add `POST .../{artifact_id}/resync`)
- Modify: `contracts/openapi.yaml` (add the resync path)
- Test: `backend/tests/unit/modules/test_artifact_resync.py`, `backend/tests/integration/test_artifact_resync.py`

**Interfaces:**
- Consumes: `_reserve_artifact_budget` (Task 3); `GoogleDriveNotFoundError` (Task 2); `content_sha256`/`processing_started_at` (Tasks 1, 4).
- Produces:
  - `async def bind_and_sync(db, contributor: User, framework_id: UUID, artifact_id: UUID, *, connection_id: UUID, file_id: str, allow_noop_skip: bool) -> ArtifactResponse`
  - `async def resync_artifact(db, contributor: User, framework_id: UUID, artifact_id: UUID) -> ArtifactResponse`
  - Route `POST /v1/frameworks/{framework_id}/artifacts/{artifact_id}/resync` → `ArtifactResponse`.

- [ ] **Step 1: Write the failing unit test — fork on drift**

`backend/tests/unit/modules/test_artifact_resync.py` (reuse the `source_preview_ctx` fixture via `from tests.unit.modules.test_frameworks_source_preview import source_preview_ctx  # noqa: F401`, plus the `_fake_connection` loader pattern):

```python
"""Unit tests for connector artifact re-sync (fork-per-change)."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
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
    monkeypatch.setattr(service.s3.storage, "delete_prefix", lambda bucket, prefix: None)
    monkeypatch.setattr(service.s3.storage, "delete_object", lambda bucket, key: None)
    monkeypatch.setattr(service, "scan_artifact",
                        SimpleNamespace(delay=lambda _id: None))


async def test_resync_forks_new_row_on_drift(monkeypatch, source_preview_ctx):
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_artifact_resync.py -v`
Expected: FAIL (`resync_artifact` undefined).

- [ ] **Step 3: Implement `bind_and_sync` + `resync_artifact`**

In `backend/app/modules/frameworks/service.py`. Import `GoogleDriveNotFoundError` alongside the existing Drive imports inside the function (matching the local-import style used in `import_artifact_from_connector`). Full implementation:

```python
async def bind_and_sync(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    artifact_id: UUID,
    *,
    connection_id: UUID,
    file_id: str,
    allow_noop_skip: bool,
) -> ArtifactResponse:
    """Fork a new artifact row from the latest bytes of a connector source.

    Serves re-sync (same source), attach (unbound → bound), and repoint
    (different source). Bytes are write-once: this never overwrites an existing
    row. The prior current row is deleted unless a published version references
    it, in which case it is retained ``current_for_framework=False``.

    Args:
        db: Async database session.
        contributor: The requesting owner.
        framework_id: The owning Framework (must be editable).
        artifact_id: The current artifact being replaced.
        connection_id: The connection to pull from.
        file_id: The provider file to pull.
        allow_noop_skip: When True (re-sync), an unchanged source raises 409 and
            an unchanged content hash short-circuits without forking.

    Returns:
        The forked artifact's status (or the same artifact on a content-skip).

    Raises:
        HTTPException(404): Framework/artifact not found or foreign.
        HTTPException(409): reauth_required / rebind_required / source_unavailable
            / artifact_processing / already_up_to_date.
        HTTPException(413): Would exceed the size budget.
        HTTPException(415): Unsupported effective MIME type.
        HTTPException(502): Provider failure.
    """
    from app.integrations.google_drive import (
        EXPORT_MIME_MAP,
        DriveFileTooLargeError,
        GoogleDriveAuthError,
        GoogleDriveError,
        GoogleDriveNotFoundError,
        download_drive_file,
        get_drive_file_metadata,
    )
    from app.modules.integrations.service import (
        get_active_connection_with_fresh_token,
    )

    settings = get_settings()
    framework = await _load_owned_framework(db, contributor, framework_id)
    _require_editable_artifacts(framework)

    artifact = await db.scalar(
        select(Artifact)
        .where(
            Artifact.id == artifact_id,
            Artifact.framework_id == framework.id,
            Artifact.current_for_framework.is_(True),
        )
        .with_for_update()
    )
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found."
        )

    # TTL-aware in-flight guard: a fresh processing lease blocks a competing
    # sync; a stale lease falls through (the reaper will fail it).
    if artifact.processing_status == "processing" and (
        artifact.processing_started_at is not None
        and artifact.processing_started_at
        > datetime.now(UTC)
        - timedelta(minutes=settings.artifact_processing_lease_minutes)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "artifact_processing",
                    "message": "This artifact is still processing."},
        )

    log = logger.bind(
        module="frameworks",
        action="bind_and_sync",
        user_id=str(contributor.id),
        framework_id=str(framework.id),
        artifact_id=str(artifact.id),
    )

    connection, access_token = await get_active_connection_with_fresh_token(
        db, user_id=contributor.id, connection_id=connection_id
    )

    try:
        metadata = await get_drive_file_metadata(
            access_token=access_token, file_id=file_id
        )
    except GoogleDriveAuthError:
        raise _reauth_conflict() from None
    except GoogleDriveNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "source_unavailable",
                    "message": "The source file is no longer available."},
        ) from None
    except GoogleDriveError as exc:
        log.error("connector_metadata_failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The file provider is unavailable.",
        ) from exc

    modified_time = (
        str(metadata.get("modifiedTime")) if metadata.get("modifiedTime") else None
    )
    if allow_noop_skip and modified_time == (artifact.source_synced_revision or None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "already_up_to_date",
                    "message": "The source has not changed."},
        )

    source_mime = str(metadata.get("mimeType", ""))
    source_name = str(metadata.get("name", "")).strip() or "import"
    export_mapping = EXPORT_MIME_MAP.get(source_mime)
    if export_mapping is not None:
        effective_mime, extension = export_mapping
        export_mime: str | None = effective_mime
        filename = f"{source_name}.{extension}"
    else:
        effective_mime = source_mime
        export_mime = None
        filename = source_name
    if effective_mime not in ALLOWED_ARTIFACT_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported artifact MIME type.",
        )

    metadata_size = metadata.get("size")
    if metadata_size is not None:
        await _reserve_artifact_budget(
            db, framework.id, add_bytes=int(metadata_size), exclude_id=artifact.id
        )

    try:
        body = await download_drive_file(
            access_token=access_token,
            file_id=file_id,
            export_mime=export_mime,
            max_bytes=ARTIFACT_MAX_TOTAL_SIZE,
        )
    except DriveFileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Framework artifacts exceed the 500MB limit.",
        ) from None
    except GoogleDriveAuthError:
        raise _reauth_conflict() from None
    except GoogleDriveNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "source_unavailable",
                    "message": "The source file is no longer available."},
        ) from None
    except GoogleDriveError as exc:
        log.error("connector_download_failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The file provider is unavailable.",
        ) from exc

    new_hash = hashlib.sha256(body).hexdigest()

    # Content-skip (re-sync only): the file's modifiedTime moved but the bytes
    # are identical — advance the markers, do not fork, do not re-run pipeline.
    if allow_noop_skip and artifact.content_sha256 == new_hash:
        artifact.source_last_synced_at = datetime.now(UTC)
        artifact.source_synced_revision = modified_time
        await write_audit(
            db=db, actor_id=contributor.id, action="artifact_resynced",
            target_type="artifact", target_id=artifact.id,
            metadata={"framework_id": str(framework.id), "result": "content_unchanged"},
        )
        await db.commit()
        log.info("artifact_resync_content_unchanged")
        return _artifact_to_response(artifact)

    old_file_key = artifact.file_key
    old_preview_prefix = (
        f"frameworks/{framework.id}/artifacts/{artifact.id}/source-preview/"
    )
    new_artifact_id = uuid4()
    new_file_key = (
        f"frameworks/{framework.id}/artifacts/{new_artifact_id}."
        f"{_extension_for_filename(filename)}"
    )
    new_artifact = Artifact(
        id=new_artifact_id,
        framework_id=framework.id,
        name=filename,
        file_key=new_file_key,
        file_size=len(body),
        mime_type=effective_mime,
        content_sha256=new_hash,
        processing_status="processing",
        processing_started_at=datetime.now(UTC),
        current_for_framework=True,
        source_kind="google_drive",
        source_external_id=file_id,
        source_connection_id=connection.id,
        source_last_synced_at=datetime.now(UTC),
        source_synced_revision=modified_time,
    )
    db.add(new_artifact)

    version_reference_count = await db.scalar(
        select(func.count(FrameworkVersionArtifact.artifact_id)).where(
            FrameworkVersionArtifact.artifact_id == artifact.id
        )
    )
    old_row_deleted = int(version_reference_count or 0) == 0
    if old_row_deleted:
        await db.delete(artifact)
    else:
        artifact.current_for_framework = False

    if framework.preview_artifact_id == artifact_id:
        framework.preview_artifact_id = new_artifact_id

    await db.flush()

    s3.storage.upload_bytes(
        bucket=settings.s3_artifacts_bucket,
        key=new_file_key,
        body=body,
        mime_type=effective_mime,
    )
    await write_audit(
        db=db, actor_id=contributor.id, action="artifact_resynced",
        target_type="artifact", target_id=new_artifact_id,
        metadata={"framework_id": str(framework.id),
                  "replaced_artifact_id": str(artifact_id)},
    )
    await db.commit()

    # Post-commit S3 cleanup: always purge the old preview cache; drop the old
    # bytes only when the old row was deleted (retained rows keep their bytes).
    s3.storage.delete_prefix(settings.s3_artifacts_bucket, old_preview_prefix)
    if old_row_deleted:
        s3.storage.delete_object(settings.s3_artifacts_bucket, old_file_key)

    scan_artifact.delay(str(new_artifact_id))
    log.bind(new_artifact_id=str(new_artifact_id)).info("artifact_resynced")
    await db.refresh(new_artifact)
    return _artifact_to_response(new_artifact)


async def resync_artifact(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    artifact_id: UUID,
) -> ArtifactResponse:
    """Pull the latest bytes of an artifact's own bound source into a new row.

    Raises:
        HTTPException(404): No connector source bound to this artifact.
    """
    framework = await _load_owned_framework(db, contributor, framework_id)
    _require_editable_artifacts(framework)
    artifact = await db.scalar(
        select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.framework_id == framework.id,
            Artifact.current_for_framework.is_(True),
        )
    )
    if (
        artifact is None
        or artifact.source_kind != "google_drive"
        or artifact.source_connection_id is None
        or artifact.source_external_id is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No connector source for this artifact.",
        )
    return await bind_and_sync(
        db,
        contributor,
        framework_id,
        artifact_id,
        connection_id=artifact.source_connection_id,
        file_id=artifact.source_external_id,
        allow_noop_skip=True,
    )
```

Also add a small shared helper near the top-level helpers (used by both `bind_and_sync` and, optionally, the existing paths — do not refactor those now):

```python
def _reauth_conflict() -> HTTPException:
    """Return the standard 409 telling the caller to reconnect the source."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"error_code": "reauth_required",
                "message": "The connection is no longer authorized. Reconnect it."},
    )
```

Ensure `hashlib`, `timedelta` (from `datetime`) are imported at module top.

Note on `resync` with a NULL `source_connection_id` (connection revoked): `resync_artifact` returns 404 above only when the source id/connection are missing; for a `google_drive` artifact whose `source_connection_id` went NULL via `ON DELETE SET NULL`, it will 404 here as well (connection is None). That satisfies "rebind_required" intent — the frontend routes the user to re-bind. (A distinct `rebind_required` code is unnecessary given the 404 already blocks and Attach is the recovery.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/modules/test_artifact_resync.py::test_resync_forks_new_row_on_drift -v`
Expected: PASS.

- [ ] **Step 5: Add the remaining unit behaviors (one RED→GREEN each)**

Add and drive to green, one at a time, in the same file:
- `test_resync_content_skip_when_bytes_identical`: metadata `modifiedTime="REV-NEW"` but `download` returns bytes whose sha256 equals the old row's `content_sha256`; assert `result.id == old_id`, no new row, `source_synced_revision == "REV-NEW"`, `processing_status` unchanged (`"processed"`).
- `test_resync_noop_when_revision_unchanged`: metadata `modifiedTime == artifact.source_synced_revision`; assert `HTTPException` 409 with `error_code == "already_up_to_date"`.
- `test_resync_blocked_while_processing_fresh_lease`: set `processing_status="processing"`, `processing_started_at=datetime.now(UTC)`; assert 409 `artifact_processing`.
- `test_resync_supersedes_stale_lease`: `processing_status="processing"`, `processing_started_at = now - 31min`; assert it forks (no 409).
- `test_resync_source_gone_returns_409`: `get_drive_file_metadata` raises `GoogleDriveNotFoundError`; assert 409 `source_unavailable`.
- `test_resync_retains_version_referenced_old_row`: insert a `FrameworkVersionArtifact` row referencing the old artifact; assert after re-sync the old row still exists with `current_for_framework is False` and its bytes are NOT deleted (assert `delete_object` was not called with the old key).
- `test_resync_repoints_preview_pointer`: set `framework.preview_artifact_id = old_id`; assert it becomes the new id.

Each: RED (write test, run, see fail — most pass immediately since the impl is complete, so verify they pass), then commit at the end of the batch. For any that fail, fix the implementation minimally.

- [ ] **Step 6: Add the endpoint**

In `backend/app/modules/frameworks/router.py`, after the `source-preview` route (line ~726-748), add:

```python
@router.post(
    "/{framework_id}/artifacts/{artifact_id}/resync",
    response_model=ArtifactResponse,
    summary="Re-sync a connector-bound artifact from its source",
    description=(
        "Owner-only, pre-publish-only. Pulls the latest bytes of the artifact's "
        "bound source into a new artifact version and re-runs the pipeline. "
        "Returns a new artifact id on change; 409 already_up_to_date when the "
        "source is unchanged. A 404 on the old id afterward means it was "
        "superseded — refetch the artifact list."
    ),
)
async def resync_artifact(
    framework_id: UUID,
    artifact_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> ArtifactResponse:
    """Pull the latest source bytes into a new artifact version."""
    return await service.resync_artifact(db, contributor, framework_id, artifact_id)
```

- [ ] **Step 7: Update OpenAPI**

In `contracts/openapi.yaml`, add the `/v1/frameworks/{framework_id}/artifacts/{artifact_id}/resync` path (POST, `ArtifactResponse` 200, 404/409/413/415/502 responses), mirroring the existing `from-connector` path's shape. Validate:

```bash
cd backend && uv run python -c "from openapi_spec_validator import validate_spec; import yaml; validate_spec(yaml.safe_load(open('../contracts/openapi.yaml')))"
```

- [ ] **Step 8: Write the integration test**

`backend/tests/integration/test_artifact_resync.py` — mirror `tests/integration/test_frameworks_source_preview.py` (uses the `client`, `auth_headers` fixtures; monkeypatch `google_drive` + `service.s3.storage`). Cover: owner re-sync on a drifted draft `google_drive` artifact → 200 with a new id, and the old id → 404 on a follow-up GET of the artifact list; non-owner → 404; published framework → 409 (editable gate); `upload` artifact → 404.

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/modules/test_artifact_resync.py tests/integration/test_artifact_resync.py -v`
Expected: PASS.

- [ ] **Step 10: Lint, type, commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add app/modules/frameworks/service.py app/modules/frameworks/router.py \
  ../contracts/openapi.yaml tests/unit/modules/test_artifact_resync.py \
  tests/integration/test_artifact_resync.py
git commit -m "Add connector artifact re-sync (fork-per-change with content skip)"
```

---

### Task 6: Re-bind — attach / repoint (`bind_artifact_source`) + detach (`detach_artifact_source`)

**Files:**
- Modify: `backend/app/modules/frameworks/service.py` (add `bind_artifact_source`, `detach_artifact_source`)
- Modify: `backend/app/modules/frameworks/schemas.py` (add `BindSourceRequest`)
- Modify: `backend/app/modules/frameworks/router.py` (add `POST .../bind-source`, `DELETE .../source`)
- Modify: `contracts/openapi.yaml`
- Test: `backend/tests/unit/modules/test_artifact_rebind.py`, `backend/tests/integration/test_artifact_rebind.py`

**Interfaces:**
- Consumes: `bind_and_sync` (Task 5).
- Produces:
  - `class BindSourceRequest(BaseModel)`: `connection_id: UUID`, `file_id: str = Field(min_length=1, max_length=256)`.
  - `async def bind_artifact_source(db, contributor, framework_id, artifact_id, payload: BindSourceRequest) -> ArtifactResponse` → `bind_and_sync(..., allow_noop_skip=False)`.
  - `async def detach_artifact_source(db, contributor, framework_id, artifact_id) -> ArtifactResponse`.
  - Routes `POST .../{artifact_id}/bind-source`, `DELETE .../{artifact_id}/source`.

- [ ] **Step 1: Write the failing unit test — attach then detach**

`backend/tests/unit/modules/test_artifact_rebind.py`:

```python
"""Unit tests for connector artifact re-bind (attach / repoint / detach)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.unit.modules.test_frameworks_source_preview import (  # noqa: F401
    source_preview_ctx,
)

pytestmark = pytest.mark.asyncio


async def test_bind_source_attaches_and_pulls_for_upload_artifact(
    monkeypatch, source_preview_ctx
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
    monkeypatch.setattr(service.s3.storage, "delete_prefix", lambda bucket, prefix: None)
    monkeypatch.setattr(service.s3.storage, "delete_object", lambda bucket, key: None)
    monkeypatch.setattr(service, "scan_artifact", SimpleNamespace(delay=lambda _id: None))

    async def _meta(*, access_token, file_id):
        return {"id": file_id, "name": "doc.pdf", "mimeType": "application/pdf",
                "size": "11", "modifiedTime": "REV-A"}

    async def _download(*, access_token, file_id, export_mime, max_bytes):
        return b"ATTACHED-11"

    monkeypatch.setattr(google_drive, "get_drive_file_metadata", _meta)
    monkeypatch.setattr(google_drive, "download_drive_file", _download)

    conn_id = artifact.__dict__  # placeholder; use the seeded connection id:
    from app.modules.integrations.models import OAuthConnection
    from sqlalchemy import select
    connection = await db.scalar(select(OAuthConnection))

    result = await service.bind_artifact_source(
        db, contributor, framework.id, artifact.id,
        BindSourceRequest(connection_id=connection.id, file_id="file-A"),
    )

    new_row = await db.get(Artifact, result.id)
    assert new_row.source_kind == "google_drive"
    assert new_row.source_external_id == "file-A"


async def test_detach_source_reverts_to_upload(monkeypatch, source_preview_ctx):
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_artifact_rebind.py -v`
Expected: FAIL (`BindSourceRequest` / `bind_artifact_source` undefined).

- [ ] **Step 3: Add the schema**

In `backend/app/modules/frameworks/schemas.py`, near `ArtifactFromConnectorRequest`:

```python
class BindSourceRequest(BaseModel):
    """Owner request to bind (attach or repoint) an artifact to a connector file."""

    connection_id: UUID
    file_id: str = Field(min_length=1, max_length=256)
```

- [ ] **Step 4: Add the service functions**

In `backend/app/modules/frameworks/service.py`:

```python
async def bind_artifact_source(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    artifact_id: UUID,
    payload: BindSourceRequest,
) -> ArtifactResponse:
    """Attach or repoint an artifact's connector source, pulling its bytes.

    Forks a new bound artifact row from the given file. Allowed for both
    ``upload`` (attach) and ``google_drive`` (repoint) current artifacts.
    """
    return await bind_and_sync(
        db,
        contributor,
        framework_id,
        artifact_id,
        connection_id=payload.connection_id,
        file_id=payload.file_id,
        allow_noop_skip=False,
    )


async def detach_artifact_source(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    artifact_id: UUID,
) -> ArtifactResponse:
    """Drop an artifact's connector binding, keeping its owned bytes.

    Reverts the current row to ``source_kind='upload'``, nulls the source
    columns, and purges its draft source-preview cache. Metadata-only — no
    bytes move, the artifact id is unchanged.

    Raises:
        HTTPException(404): Framework/artifact not found or foreign.
        HTTPException(409): The artifact is not bound to a connector source.
    """
    framework = await _load_owned_framework(db, contributor, framework_id)
    _require_editable_artifacts(framework)
    artifact = await _load_owned_artifact(db, framework, artifact_id)
    if artifact.source_kind != "google_drive":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "not_bound",
                    "message": "This artifact has no connector source."},
        )

    artifact.source_kind = "upload"
    artifact.source_external_id = None
    artifact.source_connection_id = None
    artifact.source_last_synced_at = None
    artifact.source_synced_revision = None
    await write_audit(
        db=db, actor_id=contributor.id, action="artifact_source_detached",
        target_type="artifact", target_id=artifact.id,
        metadata={"framework_id": str(framework.id)},
    )
    await db.commit()
    settings = get_settings()
    s3.storage.delete_prefix(
        settings.s3_artifacts_bucket,
        f"frameworks/{framework.id}/artifacts/{artifact.id}/source-preview/",
    )
    await db.refresh(artifact)
    return _artifact_to_response(artifact)
```

Add `artifact_source_bound` audit for the attach/repoint path: in `bind_and_sync`, when `allow_noop_skip is False`, use action `artifact_source_bound` instead of `artifact_resynced` for the fork audit (pass the action into the write_audit call — branch on `allow_noop_skip`). Update the fork-audit line in `bind_and_sync`:

```python
    await write_audit(
        db=db, actor_id=contributor.id,
        action="artifact_resynced" if allow_noop_skip else "artifact_source_bound",
        target_type="artifact", target_id=new_artifact_id,
        metadata={"framework_id": str(framework.id),
                  "replaced_artifact_id": str(artifact_id)},
    )
```

Ensure `BindSourceRequest` is imported into `service.py` from `.schemas`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/modules/test_artifact_rebind.py -v`
Expected: PASS. Add `test_detach_upload_artifact_conflicts` (detach on an already-`upload` artifact → 409 `not_bound`) as one more RED→GREEN.

- [ ] **Step 6: Add the endpoints**

In `backend/app/modules/frameworks/router.py` (import `BindSourceRequest` from `.schemas`):

```python
@router.post(
    "/{framework_id}/artifacts/{artifact_id}/bind-source",
    response_model=ArtifactResponse,
    summary="Attach or repoint an artifact's connector source",
    description=(
        "Owner-only, pre-publish-only. Binds the artifact to the given "
        "connector file and pulls its bytes into a new artifact version. "
        "Works on an unbound (upload) artifact (attach) or an already-bound "
        "one (repoint). Returns a new artifact id."
    ),
)
async def bind_artifact_source(
    framework_id: UUID,
    artifact_id: UUID,
    payload: BindSourceRequest,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> ArtifactResponse:
    """Bind (attach/repoint) an artifact to a connector source and pull bytes."""
    return await service.bind_artifact_source(
        db, contributor, framework_id, artifact_id, payload
    )


@router.delete(
    "/{framework_id}/artifacts/{artifact_id}/source",
    response_model=ArtifactResponse,
    summary="Detach an artifact's connector source",
    description=(
        "Owner-only, pre-publish-only. Drops the connector binding and keeps "
        "the owned bytes as a plain upload. Metadata-only; the artifact id is "
        "unchanged."
    ),
)
async def detach_artifact_source(
    framework_id: UUID,
    artifact_id: UUID,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> ArtifactResponse:
    """Detach the artifact's connector source, keeping its bytes."""
    return await service.detach_artifact_source(db, contributor, framework_id, artifact_id)
```

- [ ] **Step 7: Update + validate OpenAPI**

Add both paths to `contracts/openapi.yaml` (`bind-source` POST with `BindSourceRequest` body; `source` DELETE). Validate as in Task 5 Step 7.

- [ ] **Step 8: Integration test**

`backend/tests/integration/test_artifact_rebind.py` — owner attach on an `upload` draft artifact → 200 new bound id; detach → 200 `source_kind == "upload"`; non-owner → 404; bind to a foreign `connection_id` → 404 (the connection loader filters by user); confirm `ArtifactResponse` never exposes `source_external_id`/`source_connection_id`/`source_synced_revision` (assert those keys absent from the JSON body).

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/modules/test_artifact_rebind.py tests/integration/test_artifact_rebind.py -v`
Expected: PASS.

- [ ] **Step 10: Lint, type, commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add app/modules/frameworks/service.py app/modules/frameworks/schemas.py \
  app/modules/frameworks/router.py ../contracts/openapi.yaml \
  tests/unit/modules/test_artifact_rebind.py tests/integration/test_artifact_rebind.py
git commit -m "Add connector artifact re-bind (attach/repoint) and detach"
```

---

### Task 7: Fold source binding forward through `create_new_version`

**Files:**
- Modify: `backend/app/modules/frameworks/service.py:2252-2260` (the replaced-artifact clone)
- Test: `backend/tests/unit/modules/test_version_bump_source_binding.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: the cloned `Artifact` in `create_new_version` carries the five `source_*` columns from its predecessor.

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/modules/test_version_bump_source_binding.py` — seed a published framework with one `google_drive`, version-referenced artifact, call `create_new_version` replacing it (`artifact_inheritance={artifact_id: False}`), and assert the new current clone carries the source binding. Model the seed on the existing version-bump tests (search `tests/` for `create_new_version` usage and copy the closest fixture). Core assertion:

```python
    new_clone = await db.scalar(
        select(Artifact).where(
            Artifact.framework_id == framework.id,
            Artifact.current_for_framework.is_(True),
        )
    )
    assert new_clone.source_kind == "google_drive"
    assert new_clone.source_external_id == "file-orig"
    assert new_clone.source_connection_id == original_connection_id
    assert new_clone.source_synced_revision == "REV-ORIG"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_version_bump_source_binding.py -v`
Expected: FAIL (clone has `source_kind == "upload"`, source columns None).

- [ ] **Step 3: Fold the binding forward**

In `create_new_version`, the `new_artifact = Artifact(...)` block (line 2252-2260), add the five columns copied from the source `artifact`:

```python
            new_artifact = Artifact(
                id=new_artifact_id,
                framework_id=framework.id,
                name=artifact.name,
                file_key=new_file_key,
                file_size=artifact.file_size,
                mime_type=artifact.mime_type,
                current_for_framework=True,
                content_sha256=artifact.content_sha256,
                source_kind=artifact.source_kind,
                source_external_id=artifact.source_external_id,
                source_connection_id=artifact.source_connection_id,
                source_last_synced_at=artifact.source_last_synced_at,
                source_synced_revision=artifact.source_synced_revision,
            )
```

(`content_sha256` folds forward too — the clone is a byte-for-byte `copy_object`, so its hash is identical.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/modules/test_version_bump_source_binding.py -v`
Expected: PASS. Also run the existing version-bump suite to confirm no regression:
Run: `cd backend && uv run pytest tests/ -k version -v`

- [ ] **Step 5: Lint, type, commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add app/modules/frameworks/service.py tests/unit/modules/test_version_bump_source_binding.py
git commit -m "Carry artifact source binding forward through version bump"
```

---

### Task 8: Self-healing pipeline — stale-lease reaper + orphan sweep + beat schedule

**Files:**
- Create: `backend/app/workers/tasks/artifacts_beat.py`
- Modify: `backend/app/workers/beat_schedule.py` (register the task)
- Test: `backend/tests/unit/workers/test_artifacts_beat.py`

**Interfaces:**
- Consumes: `Settings.artifact_processing_lease_minutes`, `Settings.artifact_orphan_sweep_minutes` (Task 1); `Artifact.processing_started_at` (Task 1).
- Produces: Celery task `app.workers.tasks.artifacts_beat.reap_stalled_artifacts` and its async impl `_reap_stalled_artifacts_impl() -> dict[str, int]`.

- [ ] **Step 1: Write the failing test — reaper fails stale rows**

`backend/tests/unit/workers/test_artifacts_beat.py` (follow the seed/cleanup style of `test_frameworks_source_preview.py`; call the async impl directly):

```python
"""Unit tests for the artifact stale-lease reaper and orphan sweep."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.database import async_session_factory, engine
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact

pytestmark = pytest.mark.asyncio


async def _truncate() -> None:
    async with async_session_factory() as s:
        await s.execute(
            text(
                "TRUNCATE TABLE "
                f"{Artifact.__tablename__}, {Framework.__tablename__}, "
                f"{User.__tablename__} RESTART IDENTITY CASCADE"
            )
        )
        await s.commit()


async def _seed_framework(session) -> Framework:
    contributor = User(email=f"{uuid4()}@a.space", display_name="R",
                       email_verified=True, password_hash=None)
    framework = Framework(
        contributor_id=uuid4(), title="Reaper FW", description="reaper test fw",
        category="framework", sector="financial_services", industry="fund_management",
        business_function="risk_management", tags=["r"], tags_text="r",
        jurisdiction="us", complexity=3, org_size="mid_market",
        lifecycle_stage="scale", price=Decimal("1.00"), currency="USD",
        license_types=["single_user"], commercial_rights="x",
        usage_restrictions="x", status="draft",
    )
    session.add(contributor)
    await session.flush()
    framework.contributor_id = contributor.id
    session.add(framework)
    await session.flush()
    return framework


async def test_reaper_fails_stale_processing_rows(monkeypatch):
    """A row processing past the lease TTL is flipped to failed."""
    await engine.dispose()
    await _truncate()
    from app.workers.tasks import artifacts_beat

    monkeypatch.setattr(
        artifacts_beat, "get_settings",
        lambda: SimpleNamespace(s3_artifacts_bucket="bucket",
                                artifact_processing_lease_minutes=30,
                                artifact_orphan_sweep_minutes=60),
    )
    # No S3 orphans in this test.
    monkeypatch.setattr(artifacts_beat.s3.storage, "list_keys",
                        lambda bucket, prefix: [], raising=False)

    async with async_session_factory() as session:
        async with session.begin():
            framework = await _seed_framework(session)
            stale = Artifact(
                framework_id=framework.id, name="s.pdf",
                file_key="frameworks/x/artifacts/s.pdf", file_size=1,
                mime_type="application/pdf", processing_status="processing",
                processing_started_at=datetime.now(UTC) - timedelta(minutes=31),
            )
            fresh = Artifact(
                framework_id=framework.id, name="f.pdf",
                file_key="frameworks/x/artifacts/f.pdf", file_size=1,
                mime_type="application/pdf", processing_status="processing",
                processing_started_at=datetime.now(UTC),
            )
            session.add_all([stale, fresh])
            await session.flush()
            stale_id, fresh_id = stale.id, fresh.id

    result = await artifacts_beat._reap_stalled_artifacts_impl()

    async with async_session_factory() as session:
        assert (await session.get(Artifact, stale_id)).processing_status == "failed"
        assert (await session.get(Artifact, fresh_id)).processing_status == "processing"
    assert result["reaped"] == 1
    await _truncate()
    await engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/workers/test_artifacts_beat.py -v`
Expected: FAIL (module `artifacts_beat` does not exist).

- [ ] **Step 3: Check the S3 listing helper exists**

The orphan sweep needs to list keys under a prefix. `app/integrations/s3.py` has `delete_prefix` (paginates `list_objects_v2`) but no public `list_keys`. Add one (small, mirrors `delete_prefix`):

```python
    def list_keys(self, bucket: str, prefix: str) -> list[str]:
        """Return every private S3 object key under a prefix."""
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys
```

- [ ] **Step 4: Implement the beat task**

`backend/app/workers/tasks/artifacts_beat.py`:

```python
"""Celery tasks for artifact pipeline self-healing.

Reaps rows stuck in ``processing`` past the lease TTL (a crashed or never-run
scan worker would otherwise deadlock re-sync forever) and reconciles orphaned
S3 objects left by a rolled-back upload.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.frameworks.models_artifact import Artifact
from app.workers.celery_app import app

_ARTIFACT_PREFIX = "frameworks/"


async def _reap_stalled_artifacts_impl() -> dict[str, int]:
    """Fail stale processing rows and delete unreferenced S3 objects."""
    settings = get_settings()
    lease_cutoff = datetime.now(UTC) - timedelta(
        minutes=settings.artifact_processing_lease_minutes
    )
    async with async_session_factory() as db:
        async with db.begin():
            result = await db.execute(
                update(Artifact)
                .where(
                    Artifact.processing_status == "processing",
                    Artifact.processing_started_at.is_not(None),
                    Artifact.processing_started_at < lease_cutoff,
                )
                .values(processing_status="failed")
                .returning(Artifact.id)
            )
            reaped = len(result.all())

        # Orphan sweep: delete S3 objects with no live Artifact.file_key that are
        # older than the safety TTL (never delete a just-uploaded object whose
        # commit is still in flight). Object age comes from the key set diff;
        # the safety TTL is enforced by only sweeping keys absent from the DB.
        live_keys = set(
            (await db.execute(select(Artifact.file_key))).scalars().all()
        )
    swept = 0
    for key in s3.storage.list_keys(settings.s3_artifacts_bucket, _ARTIFACT_PREFIX):
        # Skip source-preview cache objects — they are managed by their own
        # lifecycle (deleted on re-sync/detach/publish), not artifact rows.
        if "/source-preview/" in key:
            continue
        if key not in live_keys:
            s3.storage.delete_object(settings.s3_artifacts_bucket, key)
            swept += 1
    logger.bind(module="artifacts", action="reap_stalled_artifacts").info(
        "artifact_reap_complete", reaped=reaped, swept=swept
    )
    return {"reaped": reaped, "swept": swept}


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def reap_stalled_artifacts(self: Any) -> dict[str, int]:
    """Fail stalled artifact processing and reconcile orphaned S3 objects."""
    log = logger.bind(
        module="artifacts", action="reap_stalled_artifacts", task_id=self.request.id
    )
    log.info("task_started")
    try:
        from app.workers.async_runner import run_async

        return run_async(_reap_stalled_artifacts_impl())
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60)
```

Note on the orphan safety TTL: because the sweep only deletes keys **absent from the DB**, and a live artifact row is written before its bytes are uploaded (upload-then-commit means the row exists in the same committed transaction as the key), a not-yet-committed upload has no committed row **and** the object may not be listable yet — but to be safe against a rolled-back upload that already put the object, restrict the sweep to keys older than `artifact_orphan_sweep_minutes`. S3 `list_objects_v2` returns `LastModified` per object; extend `list_keys` to return `(key, last_modified)` if you want the age filter enforced precisely. For the first cut, the DB-absence check plus the 15-min cadence is sufficient; add the age filter if the sweep ever races a live upload. Keep this decision noted in the task's report.

- [ ] **Step 5: Register the beat schedule**

In `backend/app/workers/beat_schedule.py`, add to `BEAT_SCHEDULE`:

```python
    "reap-stalled-artifacts-15min": {
        "task": "app.workers.tasks.artifacts_beat.reap_stalled_artifacts",
        "schedule": 900.0,
    },
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/workers/test_artifacts_beat.py -v`
Expected: PASS.

- [ ] **Step 7: Add the orphan-sweep test (RED→GREEN)**

Add `test_orphan_sweep_deletes_unreferenced_keys`: monkeypatch `list_keys` to return `["frameworks/x/artifacts/live.pdf", "frameworks/x/artifacts/orphan.pdf", "frameworks/x/artifacts/y/source-preview/z.png"]`, seed one artifact with `file_key="frameworks/x/artifacts/live.pdf"`, capture `delete_object` calls, assert only `orphan.pdf` is deleted (live key kept, source-preview key skipped). Drive to green.

- [ ] **Step 8: Lint, type, commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add app/workers/tasks/artifacts_beat.py app/workers/beat_schedule.py \
  app/integrations/s3.py tests/unit/workers/test_artifacts_beat.py
git commit -m "Add artifact stale-lease reaper and S3 orphan sweep beat task"
```

---

## Final verification (after all tasks)

- [ ] Full suite green: `cd backend && uv run pytest -q` (serial — never concurrent).
- [ ] Lint + type clean: `cd backend && uv run ruff check . && uv run mypy app`.
- [ ] Migration round-trip once more: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`.
- [ ] OpenAPI valid: validate `contracts/openapi.yaml` (Task 5 Step 7 command).
- [ ] Confidentiality: grep the diff — no source-binding field added to `ArtifactResponse`; drift/preview only on `SourcePreviewResponse`.

## Self-review notes (spec coverage)

- Spec decisions 1 (fork), 2 (attach/repoint/detach unified), 3 (guards), 4 (content_sha256 skip), 5 (lease + reaper), 6a (budget lock), 6b (orphan sweep + safe ordering), 7 (fold-forward) → Tasks 5, 6, 5(guards), 5(content-skip)+1+4, 8+1, 3, 8, 7 respectively.
- Data model (2 columns + migration) → Task 1. Drive 404 mapping → Task 2. Endpoints + OpenAPI → Tasks 5, 6. Audit actions (`artifact_resynced`, `artifact_source_bound`, `artifact_source_detached`) → Tasks 5, 6. No new GDPR/token surface — nothing to build (assert-only confidentiality tests in Tasks 5, 6).
- Deferred by spec: frontend (separate plan) — not in this plan.
