# Framework Artifact Connectors — Phase C (Re-Sync + Re-Bind) — Design

- **Date:** 2026-07-11
- **Status:** Approved — ready for implementation plan
- **Author:** William Ikeji (architect) + agent
- **Module:** `frameworks` (artifacts) + `integrations` + `workers`
- **Parent spec:** `docs/superpowers/specs/2026-06-28-framework-artifact-connectors-design.md`
- **Predecessor:** Phase B (source binding + draft live-mirror preview) — shipped
- **Related FRs:** FR-FWK-* (artifact upload, versioning, publish/review workflow), FR-GDPR-*

## Context

Phase A copied connector bytes into our S3. Phase B recorded **where** those bytes came from
(`source_kind`, `source_external_id`, `source_connection_id`, `source_last_synced_at`,
`source_synced_revision`) and showed a draft-only thumbnail + "Source updated since import"
drift badge — a **display-only** signal. Phase B explicitly moved **no new bytes**.

Phase C delivers the action the badge implies: **pull the changed source bytes into the draft**
("re-sync"), and manage the binding itself — **attach** a source to an unbound artifact,
**repoint** to a different file, or **detach** back to a plain upload ("re-bind"). It does this
**without weakening any marketplace invariant**: every byte that becomes sellable still lands in
our S3 and passes the full pipeline, and no published version's bytes are ever mutated.

This spec records the decisions reached grilling the Phase C design on 2026-07-11, including a
hardening pass that promoted three would-be "accepted risks" into first-class fixes.

## Core principle (unchanged from parent)

> A connected external file may live-mirror into Auracles **only until the artifact is
> published**. Re-sync pulls new bytes into a **new immutable artifact row** in the current
> draft; it never overwrites bytes that any published version references. Published Frameworks
> re-sync only by first creating a new draft version (`create_new_version`), preserving
> immutability by construction.

## Locked decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Re-sync mechanics: overwrite bytes in place, or fork a new artifact row? | **Always fork a new row.** New `Artifact` (new id, new `file_key`, copied+advanced binding, fresh pipeline). Old row: `current_for_framework=False` if referenced by a `framework_version_artifacts` snapshot, else delete row+bytes. One code path; write-once bytes; immutability holds by construction (mirrors `create_new_version`'s clone + `delete_artifact`'s retain guard). Cost: the artifact id changes each sync — acceptable for a draft. |
| 2 | Which re-bind operations are in scope? | **Attach + Repoint + Detach**, unified. Attach (bind a source to an unbound artifact) and Repoint (swap to a different file/connection) are the **same operation** as re-sync — one `bind_and_sync(connection_id, file_id)` core that forks a new row from the given file; the entry points differ only by precondition. Detach is metadata-only (drop binding → `upload`). Repoint is **not** a separate verb. |
| 3 | When does re-sync refuse? | **No-op** (`current modifiedTime == source_synced_revision`) → `409 already_up_to_date`. **In-flight** (current row `processing` within TTL) → `409 artifact_processing`. **Revoked** (`source_connection_id IS NULL` on re-sync) → `409 rebind_required`. **Source gone** (Drive 404) → `409 source_unavailable`. Non-editable Framework → editable gate `409`. Detach is allowed anytime. |
| 4 | Weak `modifiedTime` validator → false-positive re-sync forks identical bytes + burns a pipeline run. | **Content-addressed skip (rsync standard).** Add `artifacts.content_sha256`. Re-sync: if `modifiedTime` moved but the downloaded bytes' sha256 equals the old row's `content_sha256`, **do not fork** — return the same artifact, advance `source_last_synced_at`/`source_synced_revision` (clears the badge). "mtime changed, checksum identical → skip transfer, touch metadata." |
| 5 | Stuck-`processing` deadlock: if the scan worker never runs, the in-flight guard blocks re-sync forever. | **Lease + reaper (self-healing).** Add `artifacts.processing_started_at`. A Celery-beat task flips rows stuck `processing` past a TTL (30 min) → `failed` (reason `pipeline_stalled`). The in-flight guard is **TTL-aware** — a stale lease auto-supersedes. |
| 6a | Budget aggregate race: concurrent re-syncs/imports/uploads on one Framework both pass the `sum() < 500 MB` check. | **Framework-row lock.** A shared `_reserve_artifact_budget` helper takes `SELECT … FROM frameworks WHERE id FOR UPDATE` before the sum, serializing check-then-act per Framework. **All four write paths adopt it** — re-sync, bind, `import_artifact_from_connector`, and `request_artifact_upload_url` — closing the pre-existing import/upload race too. |
| 6b | Pre-commit S3 upload orphans an object on rollback. | **Keep safe ordering** (upload-then-commit; the reverse would leave a live row pointing at missing bytes — worse). The same maintenance beat **reconciles storage**: deletes objects under `frameworks/*/artifacts/*` with no matching `Artifact.file_key`, older than a TTL. |
| 7 | Version-bump drops source binding: `create_new_version` clones replaced artifacts' bytes but not their `source_*`. | **Fold-forward.** The clone copies the five `source_*` columns so binding survives a version bump — cloning bytes without their provenance is the same silent-drop bug eliminated elsewhere. |

## Data model changes

Additive Alembic migration `2026_07_11_0079_*` on `artifacts` (no existing column altered):

| column | type | null | meaning |
|--------|------|------|---------|
| `content_sha256` | `varchar(64)` | nullable | sha256 of the owned bytes; drives re-sync content-skip. NULL for legacy rows (falls through to fork — safe). |
| `processing_started_at` | `timestamptz` | nullable | wall-clock when the row entered `processing`; drives the stale-lease reaper + TTL-aware in-flight guard. |

- `content_sha256` is set **where bytes are already in hand**: inline at import and re-sync
  (the service holds `body`); for the upload path it is computed in the `scan_artifact`
  pipeline task (never hash up to 500 MB in a request thread).
- `processing_started_at` is stamped wherever `processing_status` is set to `processing`
  (import, `confirm_artifact_upload`, re-sync) and cleared/left on terminal states.
- Backwards-compatible: `alembic upgrade head` adds two nullable columns; `downgrade -1` drops
  them. Existing rows keep NULL — no backfill required.

## Service layer (`frameworks/service.py`)

### `bind_and_sync` — the fork core

```
bind_and_sync(db, contributor, framework_id, artifact_id, *, connection_id, file_id, allow_noop_skip)
```

1. Load owned Framework; `_require_editable_artifacts` (status ∈ {draft, pipeline_failed, pipeline_passed}).
2. Load current artifact `{id, framework_id, current_for_framework=True}` **`with_for_update`** (serialize concurrent re-sync). 404 if missing.
3. **In-flight guard (TTL-aware):** if `processing_status == 'processing'` and
   `processing_started_at` is within `ARTIFACT_PROCESSING_LEASE_TTL` → `409 artifact_processing`.
   (A stale lease falls through — the reaper will/has failed it.)
4. Resolve connection + fresh token via `get_active_connection_with_fresh_token(user_id=contributor.id, connection_id=…)`.
   Re-sync with `source_connection_id IS NULL` → `409 rebind_required`.
5. `get_drive_file_metadata(file_id)` → `modifiedTime, mimeType, size, name`.
   Drive auth → `409 reauth_required`; **Drive not-found → `409 source_unavailable`**; other → `502`.
6. **No-op skip (re-sync only, `allow_noop_skip=True`):** if `modifiedTime == source_synced_revision` → `409 already_up_to_date`.
7. **Budget:** `_reserve_artifact_budget(db, framework_id, add_bytes=size, exclude_id=artifact_id)` — `FOR UPDATE` on the Framework, then `sum(file_size) WHERE framework_id AND id != exclude_id`. Over budget → `413`. The same helper replaces the inline `sum()` check in `import_artifact_from_connector` (`exclude_id=None`) and `request_artifact_upload_url` (`exclude_id=None`), serializing all four write paths per Framework.
8. `download_drive_file(...)` (Office export via `EXPORT_MIME_MAP` as in import). Auth/size/other → `409`/`413`/`502`.
9. **Content-skip (re-sync only):** compute `sha256(body)`; if the old row has `content_sha256` and it matches → **no fork**: set old `source_last_synced_at=now`, `source_synced_revision=modifiedTime`, audit `artifact_resynced` (skipped), commit, return the **same** artifact.
   --- otherwise fork (DB txn) ---
10. New `Artifact`: new id + `file_key`, `mime_type=effective_mime`, `file_size=len(body)`,
    `content_sha256=<hash>`, `processing_status='processing'`, `processing_started_at=now`,
    `current_for_framework=True`, and binding — re-sync copies `source_connection_id`/`source_external_id`;
    bind sets them from `connection_id`/`file_id`; both set `source_kind='google_drive'`,
    `source_last_synced_at=now`, `source_synced_revision=modifiedTime`.
11. Old row: version-referenced (`count(framework_version_artifacts WHERE artifact_id)>0`) → `current_for_framework=False`; else `db.delete(old)`.
12. Re-point `framework.preview_artifact_id` if it was the old id.
13. `s3.upload_bytes(new_file_key, body)` (before commit — safe ordering).
14. `write_audit(artifact_resynced | artifact_source_bound)`.
15. Commit → `scan_artifact.delay(new_id)`.
16. **Post-commit S3 cleanup:** always `delete_prefix` the **old** row's `source-preview/*`; if the old row was deleted, also delete its `file_key`.

### Entry points

- **`resync_artifact(db, contributor, framework_id, artifact_id)`** — reads the artifact's own
  `source_connection_id`/`source_external_id`, calls `bind_and_sync(..., allow_noop_skip=True)`.
  Requires `source_kind == 'google_drive'` and a source id (else 404).
- **`bind_artifact_source(db, contributor, framework_id, artifact_id, payload)`** — Attach/Repoint;
  calls `bind_and_sync(..., connection_id=payload.connection_id, file_id=payload.file_id, allow_noop_skip=False)`.
  Allowed for `source_kind='upload'` (attach) and `'google_drive'` (repoint).
- **`detach_artifact_source(db, contributor, framework_id, artifact_id)`** — editable gate;
  current row only; `source_kind='upload'`, null the four source columns, `delete_prefix` its
  `source-preview/*`; audit `artifact_source_detached`; 200 same id. Already-`upload` → `409 not_bound`.

### `create_new_version` fold-forward

The replaced-artifact clone (`frameworks/service.py:2252`) copies `source_kind`,
`source_external_id`, `source_connection_id`, `source_last_synced_at`, `source_synced_revision`
onto the new `Artifact`, alongside the existing `copy_object` of the bytes.

## Endpoints (`frameworks/router.py`)

Owner-only; reuse `ArtifactResponse` (already carries benign `source_kind`; never the confidential
source fields or drift flag — those stay on the owner-only `SourcePreviewResponse`).

| verb + path | body | returns | id |
|---|---|---|---|
| `POST /v1/frameworks/{framework_id}/artifacts/{artifact_id}/resync` | none | `ArtifactResponse` | **new** (fork) or same (content-skip) |
| `POST /v1/frameworks/{framework_id}/artifacts/{artifact_id}/bind-source` | `BindSourceRequest{connection_id, file_id}` | `ArtifactResponse` | **new** (fork) |
| `DELETE /v1/frameworks/{framework_id}/artifacts/{artifact_id}/source` | none | `ArtifactResponse` | same |

`contracts/openapi.yaml` updated first; frontend client regenerated. `BindSourceRequest` is a new
Pydantic schema (`connection_id: UUID`, `file_id: str` with length/charset bounds).

**Client contract:** a `resync` that forks returns a **new** artifact id; a subsequent request
against the old id will 404 (`current_for_framework=False`). The frontend treats "404 after
resync" as "id superseded — refetch the artifact list," not an error.

## Workers (`app/workers`)

- **`scan_artifact` / processing pipeline (`tasks/artifacts.py`)** — compute and persist
  `content_sha256` for artifacts whose bytes arrived via the upload path (bytes read from S3
  during scanning). Import/re-sync already persisted it inline.
- **`reap_stalled_artifacts` (new `tasks/artifacts_beat.py`)** — idempotent, `bind=True`:
  1. `UPDATE artifacts SET processing_status='failed' … WHERE processing_status='processing' AND processing_started_at < now() - TTL`, recording reason `pipeline_stalled`.
  2. **Orphan sweep:** load all live `Artifact.file_key`; list the `frameworks/` artifact prefix; delete objects with no matching key **older than a safety TTL** (never delete a just-uploaded, not-yet-committed object).
- **Beat schedule** (`beat_schedule.py` / `schedules.py`) — register `reap_stalled_artifacts`
  every 15 min. TTLs live in config (`ARTIFACT_PROCESSING_LEASE_TTL`, orphan safety TTL).

## Security

- **Token handling unchanged** — Fernet at rest, server-side refresh, never returned, never logged.
  Re-sync/bind reuse `get_active_connection_with_fresh_token`, which scopes by `user_id` → a bind
  to another user's `connection_id` 404s (no IDOR).
- **No new SSRF surface** — byte fetches go to the Drive API host via `download_drive_file`
  (host/size-capped, as in import); no user-supplied URLs. The only allowlisted external fetch
  (thumbnail) is unchanged Phase B.
- **Immutability** — write-once bytes; a published version's referenced artifact row is retained
  (`current=False`), never overwritten. Escrow/financial invariants untouched (not in scope).
- **Confidentiality by construction** — source binding/drift never reaches `ArtifactResponse` or
  any buyer/catalog/public serializer.
- **Authorization** — every endpoint owner-only + editable-only via existing dependencies/predicates.
- **Audit** (`module="frameworks"`) — new actions `artifact_resynced`, `artifact_source_bound`,
  `artifact_source_detached`. Reaper/sweep log under `module="artifacts"` with `task_id`.
- **No new GDPR surface** — connector token revoke + `oauth_connections` purge on account deletion
  shipped in Phase B; re-sync adds no new stored token.

## What Phase C is NOT

- **Not** live-mirror of **published/sold** artifacts — permanently out of scope (parent rationale).
- **Not** in-place byte mutation — bytes are write-once; every change forks a row.
- **Not** a `force` re-sync of unchanged bytes — the content-skip returns success without a fork; there is no way to duplicate identical bytes on purpose.
- **Not** Dropbox/OneDrive — Google Drive only; the provider-generic abstraction is preserved.

## Testing (TDD — RED→GREEN per slice)

**Unit (service):**
- Re-sync forks a new row; old unreferenced row + bytes deleted; old **version-referenced** row retained `current=False`.
- Content-skip: `modifiedTime` moved but sha256 equal → **no** new row, markers advanced, same id returned.
- No-op guard: `modifiedTime` unchanged → `409 already_up_to_date`, no download.
- In-flight guard: `processing` within TTL → `409`; `processing` past TTL → allowed (supersedes).
- Revoked (`source_connection_id` NULL) → `409 rebind_required`; Drive 404 → `409 source_unavailable`.
- Budget: replace excludes the old id; over budget → `413`. `_reserve_artifact_budget` enforces the limit and is used by re-sync, bind, import, and upload-url (over-budget rejected on all four).
- Attach: bind a source to an `upload` artifact → forks bound row. Repoint: bind a different file. Detach: `upload` + nulled binding + preview cache purged; already-`upload` → `409 not_bound`.
- `preview_artifact_id` re-points to the forked row.
- `create_new_version` clone carries the five `source_*` columns forward.
- Reaper: stale `processing` → `failed(pipeline_stalled)`; fresh `processing` untouched. Idempotent.
- Orphan sweep: unreferenced key past TTL deleted; referenced key + fresh key kept.
- `content_sha256` persisted by the pipeline for upload-path artifacts.

**Integration (endpoints):**
- `POST resync` as owner on a drifted `google_drive` draft artifact → new id, old id 404s.
- `POST bind-source` attach on an `upload` artifact → bound; repoint → new bytes.
- `DELETE source` → `upload`, binding gone.
- Non-owner → 403; published Framework → editable-gate 409; upload artifact `resync` → 404.
- Source binding/drift **absent** from every `ArtifactResponse` (catalog, buyer library, owner list).

**Migration / security:**
- `upgrade head` + `downgrade -1` both succeed; existing rows → NULL new columns.
- Tokens never in any Phase-C response or log. Bind to a foreign `connection_id` → 404.

## Frontend (Next.js — deferred to a separate plan)

- Owner draft artifact card: "Re-sync" button (enabled when `source_updated`), "Change source"
  (bind), "Detach"; handle the id-superseded refetch after re-sync.
- Mobile-first, 44 px touch targets, tested at 375 px. OpenAPI-first; client regenerated.

## Risks

- **Provider byte-fetch cost on re-sync** — re-sync always downloads to hash/verify; the no-op
  guard avoids download when `modifiedTime` is unchanged, and the content-skip avoids the pipeline
  when bytes are identical. Documented, accepted.
- **Orphan sweep at scale** — full-prefix listing is bounded by the safety TTL and a 15-min
  cadence; migrate to an S3 lifecycle rule on a dedicated prefix if it becomes hot.
